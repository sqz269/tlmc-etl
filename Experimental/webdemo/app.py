import os
import json
from pathlib import Path
from functools import lru_cache

import annoy
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.stats import gaussian_kde
from dash import Dash, dcc, html, Input, Output, State, ALL
import dash

# --- Paths (robust to cwd / docker) ---
# In the repo, this file lives in Experimental/webdemo/app.py, so the project root is parent.
# In Docker, app.py is copied to /app/app.py and data is copied to /app/{embeddings,vector_index,...},
# so the "project root" is the same directory as this file.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

def pick_existing_dir(dir_name: str) -> Path:
  for d in (BASE_DIR / dir_name, PROJECT_ROOT / dir_name):
    if d.exists():
      return d
  # default (helps error messages stay stable)
  return PROJECT_ROOT / dir_name

EMBEDDINGS_DIR = pick_existing_dir("embeddings")
VECTOR_INDEX_DIR = pick_existing_dir("vector_index")

# --- Constants ---
METADATA_CSV_FILE = str(EMBEDDINGS_DIR / "id_metadata.csv")
UMAP_CSV_FILE_TEMPLATE = "umap_data_{pooling_policy}.csv"

ANN_TEMPLATE = str(VECTOR_INDEX_DIR / "annoy_index_{pooling_policy}.ann")
# Mapping UUIDs to Annoy integer IDs
VECTOR_ID_TO_KEY_TEMPLATE = (
  str(VECTOR_INDEX_DIR / "annoy_int_index_to_uuid_{pooling_policy}.csv")
)
AUDIO_API_TEMPLATE = "https://staging-api.marisad.me/api/asset/track/{track_id}/hls"

POOLING_POLICY_DIM = {"mean": 1024, "mean+max": 2048}
DEFAULT_POLICY = "mean+max"

SAMPLE_SIZE = 5000
# --- Data Loading with Caching ---


@lru_cache(maxsize=None)
def load_annoy_index(policy: str):
  """Load Annoy index for a given policy, cached in memory."""
  ann_index_path = ANN_TEMPLATE.format(pooling_policy=policy)
  if not os.path.exists(ann_index_path):
    return None

  embedding_dim = POOLING_POLICY_DIM[policy]
  index = annoy.AnnoyIndex(embedding_dim, "angular")
  index.load(ann_index_path, prefault=True)
  return index


@lru_cache(maxsize=None)
def load_data(policy: str, umap_policy: str):
  """
  Load data and return fast lookup structures.
  Args:
    policy: Pooling policy for Annoy index
    umap_policy: Pooling policy for UMAP visualization
  Returns:
    df_data: DataFrame (for global checks)
    df_umap: UMAP DataFrame
    annoy_to_track_map: Map annoy_id -> TrackID
    meta_dict: Full metadata dictionary {TrackID: {TrackName:..., ArtistName:...}}
  """
  map_path = VECTOR_ID_TO_KEY_TEMPLATE.format(pooling_policy=policy)

  if not os.path.exists(map_path):
    return None, None, None, None

  # 1. Load Mapping
  id_map_df = pd.read_csv(map_path, index_col=0)
  id_map_df.index.name = "annoy_id"
  id_map_df = id_map_df.reset_index()

  # 2. Load Metadata
  meta_df = pd.read_csv(METADATA_CSV_FILE)

  # 3. Merge
  merged_df = pd.merge(id_map_df, meta_df, on="TrackID", how="inner")
  merged_df = merged_df.set_index("TrackID")

  # 4. Create Optimizers
  annoy_to_track_map = merged_df.reset_index().set_index("annoy_id")["TrackID"].to_dict()
  
  # --- OPTIMIZATION: Convert entire DF to dict for instant row access ---
  # accessing dict['id'] is significantly faster than df.loc['id']
  meta_dict = merged_df.to_dict(orient="index")

  # 5. Load UMAP (using umap_policy)
  umap_df = None
  umap_file = UMAP_CSV_FILE_TEMPLATE.format(pooling_policy=umap_policy)
  # Prefer webdemo-local files (for Docker), else fall back to repo results/umap
  umap_path = BASE_DIR / umap_file
  if not umap_path.exists():
    umap_path = PROJECT_ROOT / "results" / "umap" / umap_file

  if umap_path.exists():
    umap_df = pd.read_csv(str(umap_path))

  return merged_df, umap_df, annoy_to_track_map, meta_dict


def add_artist_kde_contours(fig, df_umap, selected_artists, opacity=0.3):
  """
  Add KDE contours with robust type handling and fallback for small clusters.
  """
  if not selected_artists or df_umap is None or df_umap.empty:
    return

  # Color palette
  colors = [
    'rgb(255, 0, 0)', 'rgb(0, 0, 255)', 'rgb(0, 255, 0)', 'rgb(255, 165, 0)',
    'rgb(128, 0, 128)', 'rgb(255, 192, 203)', 'rgb(0, 255, 255)', 'rgb(255, 255, 0)',
    'rgb(139, 69, 19)', 'rgb(128, 128, 128)'
  ]

  # FIX 1: Ensure we are comparing strings to strings
  # Create a temporary series for filtering to avoid modifying the original DF in a loop
  artist_col_str = df_umap['ArtistName'].astype(str)

  for idx, artist in enumerate(selected_artists):
    # FIX 1 applied here
    artist_points = df_umap[artist_col_str == str(artist)][['x', 'y']].values

    # FIX 2: Lower threshold to 3 points to allow smaller artists to show
    if len(artist_points) < 3:
      print(f"Skipping {artist}: Not enough points ({len(artist_points)})")
      continue

    try:
      x = artist_points[:, 0]
      y = artist_points[:, 1]

      # FIX 3: Handle collinear points (Singular Matrix)
      # If points are too tight, add tiny jitter to allow KDE to calculate
      if np.all(x == x[0]) or np.all(y == y[0]):
         x += np.random.normal(0, 0.01, size=len(x))
         y += np.random.normal(0, 0.01, size=len(y))

      xy = np.vstack([x, y])
      
      # Try/Catch specifically for Linear Algebra errors in KDE
      try:
        kde = gaussian_kde(xy, bw_method='scott')
      except np.linalg.LinAlgError:
        # Fallback: Force a wider bandwidth if data is too singular
        kde = gaussian_kde(xy, bw_method=0.5)
      
      # Create grid
      x_span = x.max() - x.min()
      y_span = y.max() - y.min()
      
      # Ensure minimum span to avoid degenerate grids
      if x_span < 0.1:
        x_span = 1.0
      if y_span < 0.1:
        y_span = 1.0
      
      padding_x = x_span * 0.2
      padding_y = y_span * 0.2

      x_min, x_max = x.min() - padding_x, x.max() + padding_x
      y_min, y_max = y.min() - padding_y, y.max() + padding_y
      
      # Ensure x_min != x_max and y_min != y_max
      if abs(x_max - x_min) < 0.01:
        x_min -= 0.5
        x_max += 0.5
      if abs(y_max - y_min) < 0.01:
        y_min -= 0.5
        y_max += 0.5

      grid_size = min(100, max(30, int(len(artist_points) ** 0.5) * 5)) # Increased resolution
      
      # Use linspace to create 1D arrays, then meshgrid
      x_grid = np.linspace(x_min, x_max, grid_size)
      y_grid = np.linspace(y_min, y_max, grid_size)
      xx, yy = np.meshgrid(x_grid, y_grid)
      
      positions = np.vstack([xx.ravel(), yy.ravel()])
      z = np.reshape(kde(positions).T, xx.shape)
      
      # Normalize
      z_min, z_max = z.min(), z.max()
      if z_max > z_min:
        z_normalized = (z - z_min) / (z_max - z_min)
      else:
        z_normalized = z # Flat distribution

      color = colors[idx % len(colors)]
      contour_levels = [0.2, 0.5, 0.8] # Adjusted levels for better visibility

      # Add filled contours with gradient shading
      # First, add the filled regions (from lowest to highest density)
      for level_idx in range(len(contour_levels) - 1):
        level_start = contour_levels[level_idx]
        level_end = contour_levels[level_idx + 1]
        
        # Opacity increases with density (inner regions are more opaque)
        fill_opacity = opacity * (0.3 + level_idx * 0.3)
        
        # Create gradient colorscale from transparent to semi-transparent
        color_transparent = color.replace('rgb', 'rgba').replace(')', ', 0)')
        color_filled = color.replace('rgb', 'rgba').replace(')', f', {fill_opacity})')
        
        fig.add_trace(go.Contour(
          x=x_grid,
          y=y_grid,
          z=z_normalized,
          contours=dict(
            start=level_start,
            end=level_end,
            coloring='fill',
          ),
          colorscale=[[0, color_transparent], [1, color_filled]],
          showscale=False,
          name=None,
          showlegend=False,
          hoverinfo='skip',
          line=dict(width=0),  # No border lines for fills
        ))
      
      # Then add contour lines on top for definition
      for level_idx, level in enumerate(contour_levels):
        line_opacity = min(1.0, opacity * 2.5)  # Make lines more visible
        
        fig.add_trace(go.Contour(
          x=x_grid,
          y=y_grid,
          z=z_normalized,
          contours=dict(
            start=level,
            end=level,
            size=0.01,
            coloring='lines',
          ),
          line=dict(
            color=color,
            width=3 if level_idx == len(contour_levels) - 1 else 2,
          ),
          showscale=False,
          name=f'{artist}' if level_idx == 0 else None,
          showlegend=(level_idx == 0),
          hoverinfo='skip',
          opacity=line_opacity,
        ))

    except Exception as e:
      print(f"Error computing KDE for {artist}: {str(e)}")
      continue

@lru_cache(maxsize=None)
def get_base_umap_figure(policy: str, umap_policy: str, sample_size: int = SAMPLE_SIZE):
  """
  Build the base UMAP figure (cached).
  Does NOT include the highlight.
  Args:
    policy: Pooling policy for Annoy index
    umap_policy: Pooling policy for UMAP visualization
    sample_size: Number of points to sample
  """
  # Unpack 3 values now (we ignore the lookup map here)
  df_data, df_umap, _, _ = load_data(policy, umap_policy)
  
  if df_umap is None or df_umap.empty:
    fig = px.scatter()
    fig.update_layout(
      title="No UMAP data available. Please generate UMAP CSV.",
      xaxis_visible=False,
      yaxis_visible=False,
    )
    return fig

  # Sample for speed
  df_plot = df_umap.sample(min(sample_size, len(df_umap)), random_state=42)

  fig = px.scatter(
    df_plot,
    x="x",
    y="y",
    color="ArtistName",
    hover_data=["TrackName", "ArtistName", "TrackID"],
    custom_data=["TrackID"],  # used to recover TrackID on click
    title="Music Embedding Landscape (UMAP)",
    render_mode="webgl",
  )
  fig.update_layout(
    clickmode="event+select",
    height=600,
    xaxis_visible=False,
    yaxis_visible=False,
    showlegend=False,
    margin=dict(l=10, r=10, t=50, b=10),
  )
  fig.update_traces(marker=dict(size=5, opacity=0.8))

  return fig


def make_umap_figure(policy: str, selected_track_id: str = None, sample_size: int = SAMPLE_SIZE, umap_policy: str = None, selected_artists: list = None, contour_opacity: float = 0.3):
  """
  Get base figure and add highlight trace for selected track.
  Args:
    policy: Pooling policy for Annoy index
    selected_track_id: Track ID to highlight
    sample_size: Number of points to sample
    umap_policy: Pooling policy for UMAP visualization (defaults to policy if None)
    selected_artists: List of artists to show density contours for
    contour_opacity: Opacity for KDE contour fills (0-1)
  """
  if umap_policy is None:
    umap_policy = policy
    
  # 1. Get cached base figure
  base_fig = get_base_umap_figure(policy, umap_policy, sample_size)
  
  # 2. Create a lightweight copy to avoid mutating the cached object
  fig = go.Figure(base_fig)
  
  # 3. Load UMAP data for contours and track highlighting
  _, df_umap, _, _ = load_data(policy, umap_policy)
  
  # 4. Add KDE contours for selected artists (before track highlight so star is on top)
  if selected_artists and df_umap is not None:
    add_artist_kde_contours(fig, df_umap, selected_artists, contour_opacity)

  # 5. Add track highlight if selected
  if selected_track_id and df_umap is not None:
    # Assuming df_umap has TrackID column
    row = df_umap[df_umap["TrackID"] == selected_track_id]
    if not row.empty:
      # Add highlight trace - star marker for selected track
      fig.add_trace(
        go.Scatter(
          x=row["x"],
          y=row["y"],
          mode="markers",
          marker=dict(
            size=15,
            color="red",
            symbol="star",
            line=dict(width=2, color="white")
          ),
          name="Selected",
          hoverinfo="text",
          hovertext=f"Selected: {row.iloc[0]['TrackName']} - {row.iloc[0]['ArtistName']}",
          showlegend=False,
          customdata=[[selected_track_id]] # Maintain consistent click behavior
        )
      )
  
  return fig


# --- Dash App Setup ---

app = Dash(__name__)
server = app.server  # for deployment if needed

app.title = "TLMC Music Embedding Explorer (Dash)"

app.layout = html.Div(
  style={"fontFamily": "system-ui, -apple-system, BlinkMacSystemFont, sans-serif"},
  children=[
    html.Div(
      style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "0.5rem"},
      children=[
        html.H2("🎵 TLMC Music Embedding Explorer", style={"margin": "0"}),
        html.A(
          "Technical Details & Blog Post",
          href="https://blog.sqz269.me/2025/11/03/tlmc-rec-01.html",
          target="_blank",
          style={
            "fontSize": "0.9rem",
            "color": "#007bff",
            "fontWeight": "bold",
            "padding": "0.5rem 1rem",
            "border": "1px solid #007bff",
            "borderRadius": "4px",
          }
        ),
      ]
    ),
    html.Div(
      [
        html.Label("Search Policy:", style={"marginRight": "0.5rem"}),
        dcc.Dropdown(
          id="policy-dropdown",
          options=[
            {"label": k, "value": k} for k in POOLING_POLICY_DIM.keys()
          ],
          value=DEFAULT_POLICY,
          clearable=False,
          style={"width": "200px"},
        ),
        html.Label("UMAP Policy:", style={"marginLeft": "1.5rem", "marginRight": "0.5rem"}),
        dcc.Dropdown(
          id="umap-policy-dropdown",
          options=[
            {"label": k, "value": k} for k in POOLING_POLICY_DIM.keys()
          ],
          value=DEFAULT_POLICY,
          clearable=False,
          style={"width": "200px"},
        ),
        html.Label("Sample Size:", style={"marginLeft": "1.5rem", "marginRight": "0.5rem"}),
        dcc.Input(
          id="sample-size-input",
          type="number",
          value=SAMPLE_SIZE,
          min=100,
          max=50000,
          step=500,
          style={"width": "100px"},
          debounce=True,
        ),
      ],
      style={"display": "flex", "alignItems": "center", "marginBottom": "1rem"},
    ),

    # Store for global selected track id
    dcc.Store(id="selected-track-store"),
    dcc.Store(id="sample-size-store", data=SAMPLE_SIZE),
    dcc.Store(id="selected-artists-store", data=[]),
    # New stores for auto-play feature
    dcc.Store(id="current-neighbors-store", data=[]),
    dcc.Store(id="auto-play-trigger"),
    dcc.Store(id="history-store", data=[]), # Store for journey history
    dcc.Interval(id="audio-poller", interval=1000), # Check every second

    # Quick Guide (collapsible)
    html.Details(
      style={"marginBottom": "1rem", "padding": "0.5rem", "backgroundColor": "#f8f9fa", "borderRadius": "4px"},
      children=[
        html.Summary("📖 Quick Guide - How to Use", style={"cursor": "pointer", "fontWeight": "bold", "padding": "0.5rem"}),
        html.Div(
          style={"padding": "1rem", "fontSize": "0.9rem", "lineHeight": "1.6"},
          children=[
            html.P([
              html.Strong("🎵 Play Music: "),
              "Click any point on the map, or select from search results."
            ], style={"marginBottom": "0.5rem"}),
            html.P([
              html.Strong("🔍 Search: "),
              "Type artist or track name in the search box. Click results to play."
            ], style={"marginBottom": "0.5rem"}),
            html.P([
              html.Strong("🎯 Discover Similar: "),
              "Check 'Nearest Neighbors' below for recommendations. Click 'Explore Neighbor' to jump to similar tracks."
            ], style={"marginBottom": "0.5rem"}),
            html.P([
              html.Strong("🎨 Artist Density: "),
              "Select artists from dropdown to see their 'sound space'. Darker regions = more songs concentrated there."
            ], style={"marginBottom": "0.5rem"}),
            html.P([
              html.Strong("⚙️ Settings: "),
              "Adjust Search/UMAP Policy and Sample Size. Higher samples = more detail, lower = faster."
            ], style={"marginBottom": "0.5rem"}),
            html.P([
              html.Strong("💡 Tip: "),
              html.Em("Songs close together on the map sound similar. Explore by clicking around!")
            ], style={"marginBottom": "0"}),
            html.P([
              html.Strong("💡 Note: "),
              html.Em("Please be patient when loading the page. It may take a few seconds to load the data.")
            ], style={"marginBottom": "0"}),
            html.P([
              html.Strong("💡 Note: "),
              html.Em("This is a demo of the MERT embeddings and kNN search. An improved recommender system will be productionalized in the future.")
            ], style={"marginBottom": "0"}),
            html.P([
              html.Strong("🔗 Blog Post: "),
              html.A("Checkout the blog for more details!", href="https://blog.sqz269.me", target="_blank", style={"color": "#007bff", "textDecoration": "none"})
            ], style={"marginBottom": "0"}),
          ]
        )
      ]
    ),

    # Now Playing section with loading spinner
    dcc.Loading(
      id="loading-now-playing",
      type="default",  # Options: "default", "circle", "dot", "cube"
      children=html.Div(id="now-playing", style={"marginBottom": "1.5rem"}),
    ),

    # Main layout: left search/NN, right map
    html.Div(
      style={"display": "flex", "gap": "1.5rem"},
      children=[
        # Left column
        html.Div(
          style={"flex": "1"},
          children=[
            html.H3("🔍 Search & Similarity"),
            html.Label("Search by Name/Artist:"),
            dcc.Input(
              id="search-input",
              type="text",
              placeholder="Type Artist or Track Name...",
              style={
                "width": "100%",
                "padding": "0.3rem",
                "marginBottom": "0.8rem",
              },
              debounce=True,
            ),
            dcc.Loading(
              id="loading-search",
              type="default",
              children=html.Div(id="search-results", style={"marginBottom": "1rem"}),
            ),
            
            html.Hr(style={"margin": "1.5rem 0"}),

            html.Label("Selected Track ID:"),
            dcc.Input(
              id="track-id-input",
              type="text",
              placeholder="TrackID...",
              style={
                "width": "100%",
                "padding": "0.3rem",
                "marginBottom": "0.8rem",
              },
              debounce=True,
            ),
            
            html.Div(
              [
                dcc.Checklist(
                  id="auto-play-switch",
                  options=[{"label": " 🎲 Stochastic Explore (Auto-play)", "value": "enabled"}],
                  value=[],
                  style={"fontSize": "0.9rem", "fontWeight": "bold"}
                )
              ],
              style={"marginBottom": "1rem", "padding": "0.5rem", "backgroundColor": "#e9ecef", "borderRadius": "4px"}
            ),

            dcc.Loading(
              id="loading-neighbors",
              type="default",
              children=html.Div(id="neighbors-container"),
            ),

            html.Hr(style={"margin": "1.5rem 0"}),

            # Journey History
            html.Details(
              open=True,
              children=[
                html.Summary(
                    "📜 Journey History",
                    style={"cursor": "pointer", "fontWeight": "bold", "marginBottom": "0.5rem"}
                ),
                html.Div(
                    id="journey-container",
                    style={"maxHeight": "300px", "overflowY": "auto", "padding": "0 0.5rem"}
                )
              ],
              style={"marginBottom": "1rem"}
            ),
          ],
        ),
        # Right column
        html.Div(
          style={"flex": "1.5"},
          children=[
            html.H3(id="map-title"),
            html.Div(
              id="map-subtitle",
              style={"fontSize": "0.9rem", "color": "#555"},
            ),
            html.Div(
              style={"marginBottom": "0.5rem", "display": "flex", "alignItems": "center", "gap": "0.5rem"},
              children=[
                html.Label("Show Artist Density (KDE Contours):", style={"fontWeight": "bold"}),
                dcc.Dropdown(
                  id="artist-hull-selector",
                  options=[],  # Will be populated dynamically
                  value=[],
                  multi=True,
                  placeholder="Search and select artists...",
                  style={"width": "400px", "fontSize": "0.9rem"},
                ),
                html.Button(
                  "Clear All",
                  id="clear-artists-btn",
                  type="button",
                  style={
                    "padding": "0.3rem 0.8rem",
                    "fontSize": "0.85rem",
                    "cursor": "pointer",
                    "backgroundColor": "#f8f9fa",
                    "border": "1px solid #dee2e6",
                    "borderRadius": "4px",
                  }
                ),
              ]
            ),
            dcc.Loading(
              id="loading-map",
              type="circle",  # Use circle spinner for the map (less intrusive)
              children=dcc.Graph(
                id="umap-graph",
                figure=make_umap_figure(DEFAULT_POLICY),
                style={"height": "650px"},
                config={"displayModeBar": False},
              ),
            ),
          ],
        ),
      ],
    ),
  ],
)


# --- Callbacks ---


@app.callback(
  Output("sample-size-store", "data"),
  Input("sample-size-input", "value"),
)
def update_sample_size_store(sample_size):
  """Store the sample size when user changes it."""
  if sample_size and sample_size > 0:
    return sample_size
  return SAMPLE_SIZE


@app.callback(
  Output("artist-hull-selector", "options"),
  Input("policy-dropdown", "value"),
  Input("umap-policy-dropdown", "value"),
)
def populate_artist_options(policy, umap_policy):
  """Populate artist checklist based on available artists in UMAP data."""
  _, df_umap, _, _ = load_data(policy, umap_policy)
  
  if df_umap is None or df_umap.empty:
    return []
  
  # Get unique artists, filter out NaN values, and sort them
  artists = df_umap['ArtistName'].dropna().unique()
  artists = sorted([str(a) for a in artists])
  
  return [{"label": artist, "value": artist} for artist in artists]


@app.callback(
  Output("selected-artists-store", "data"),
  Output("artist-hull-selector", "value"),
  Input("artist-hull-selector", "value"),
  Input("clear-artists-btn", "n_clicks"),
  prevent_initial_call=True,
)
def update_selected_artists(selected_artists, clear_clicks):
  """Store selected artists for hull visualization."""
  ctx = dash.callback_context
  if not ctx.triggered:
    raise dash.exceptions.PreventUpdate
  
  trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
  
  # Clear button clicked
  if trigger_id == "clear-artists-btn":
    return [], []
  
  # Artist selection changed
  return selected_artists or [], dash.no_update


@app.callback(
  Output("map-title", "children"),
  Output("map-subtitle", "children"),
  Input("policy-dropdown", "value"),
  Input("umap-policy-dropdown", "value"),
  Input("sample-size-store", "data"),
)
def update_map_labels(policy, umap_policy, sample_size):
  """Update map title and subtitle based on policy and sample size."""
  title = f"🗺️ 2D Map (Search: {policy}, UMAP: {umap_policy}, Sample: {sample_size}) (Click to Play)"
  subtitle = "NOTE: Different UMAP policies may produce different visualizations interms of genre placement in the space. The artist density (KDE Contours) is calculated using Gaussian Kernel Density Estimation method."
  return title, subtitle


@app.callback(
  Output("umap-graph", "figure"),
  Input("policy-dropdown", "value"),
  Input("umap-policy-dropdown", "value"),
  Input("selected-track-store", "data"),
  Input("sample-size-store", "data"),
  Input("selected-artists-store", "data"),
)
def update_map(policy, umap_policy, selected_track_id, sample_size, selected_artists):
  """
  Update UMAP figure when policy, track selection, sample size, or artist selection changes.
  """
  if not sample_size or sample_size <= 0:
    sample_size = SAMPLE_SIZE
  return make_umap_figure(policy, selected_track_id, sample_size, umap_policy, selected_artists)


@app.callback(
  Output("search-results", "children"),
  Input("search-input", "value"),
  State("policy-dropdown", "value"),
)
def show_search_results(search_term, policy):
  if not search_term:
    return []

  # For search, we only need metadata, so umap_policy doesn't matter
  df_data, _, _, _ = load_data(policy, policy)
  if df_data is None:
    return []

  # Case-insensitive search
  mask = (
    df_data["TrackName"].astype(str).str.contains(search_term, case=False, na=False) | 
    df_data["ArtistName"].astype(str).str.contains(search_term, case=False, na=False)
  )
  results = df_data[mask].head(10)

  if results.empty:
    return html.Div("No results found.", style={"color": "#888", "fontSize": "0.9rem"})

  items = []
  for tid, row in results.iterrows():
    items.append(
      html.Div(
        html.Button(
          children=[
            html.Div(row["TrackName"], style={"fontWeight": "600", "textAlign": "left"}),
            html.Div(f"{row['ArtistName']}", style={"fontSize": "0.8rem", "color": "#666", "textAlign": "left"}),
          ],
          id={"type": "search-result", "index": tid},
          type="button",
          style={
            "width": "100%",
            "background": "transparent",
            "border": "none",
            "borderBottom": "1px solid #eee",
            "padding": "0.5rem 0",
            "cursor": "pointer",
          },
        )
      )
    )
  
  return html.Div(
      items, 
      style={"border": "1px solid #ddd", "padding": "0 0.5rem", "maxHeight": "250px", "overflowY": "auto", "borderRadius": "4px"}
  )


@app.callback(
  Output("selected-track-store", "data"),
  Output("track-id-input", "value"),
  Input("umap-graph", "clickData"),
  Input("track-id-input", "value"),
  Input({"type": "search-result", "index": ALL}, "n_clicks"),
  Input({"type": "neighbor-select", "index": ALL}, "n_clicks"),
  Input({"type": "history-select", "index": ALL}, "n_clicks"),
  Input("auto-play-trigger", "data"),
  State("policy-dropdown", "value"),
  State("selected-track-store", "data"),
  prevent_initial_call=True,
)
def on_selection_change(clickData, track_id_input_value, search_clicks, neighbor_clicks, history_clicks, auto_play_data, policy, current_track_id):
  """
  Single callback responsible for updating selected-track-store and input.
  """
  ctx = dash.callback_context
  if not ctx.triggered:
    raise dash.exceptions.PreventUpdate

  trigger_prop_id = ctx.triggered[0]["prop_id"]
  trigger_id = trigger_prop_id.split(".")[0]

  # Case: Auto-play trigger
  if trigger_id == "auto-play-trigger":
    if not auto_play_data:
      raise dash.exceptions.PreventUpdate
    return auto_play_data, auto_play_data

  # Unpack 3 values (ignore lookup here)
  # For selection validation, we only need metadata, so umap_policy doesn't matter
  df_data, _, _, _ = load_data(policy, policy)
  
  if df_data is None or df_data.empty:
    raise dash.exceptions.PreventUpdate

  # Helper to handle pattern-matched triggers (search results or neighbors)
  if "search-result" in trigger_id or "neighbor-select" in trigger_id or "history-select" in trigger_id:
    try:
      trigger_value = ctx.triggered[0]["value"]
      # Must have been clicked at least once
      if not trigger_value:
        raise dash.exceptions.PreventUpdate

      info = json.loads(trigger_id)
      clicked_track_id = info["index"]
      return clicked_track_id, clicked_track_id
    except Exception:
      raise dash.exceptions.PreventUpdate

  # Case 1: Clicked on UMAP
  if trigger_id == "umap-graph":
    if (
      not clickData
      or "points" not in clickData
      or not clickData["points"]
    ):
      raise dash.exceptions.PreventUpdate

    clicked_point = clickData["points"][0]
    if "customdata" not in clicked_point or not clicked_point["customdata"]:
      raise dash.exceptions.PreventUpdate

    clicked_track_id = clicked_point["customdata"][0]

    if clicked_track_id == current_track_id:
      raise dash.exceptions.PreventUpdate

    # Sync store + input
    return clicked_track_id, clicked_track_id

  # Case 2: User typed in the ID input
  if trigger_id == "track-id-input":
    track_id = track_id_input_value
    if not track_id:
      raise dash.exceptions.PreventUpdate

    if track_id == current_track_id:
      raise dash.exceptions.PreventUpdate

    if track_id in df_data.index:
      # Valid track: update store and keep text as is
      return track_id, track_id

    # Invalid trackID: don't change selection or text
    raise dash.exceptions.PreventUpdate

  # Fallback
  raise dash.exceptions.PreventUpdate


@app.callback(
  Output("now-playing", "children"),
  Output("neighbors-container", "children"),
  Output("current-neighbors-store", "data"),
  Input("selected-track-store", "data"),
  State("policy-dropdown", "value"),
)
def update_now_playing_and_neighbors(selected_track_id, policy):
  # Unpack 4 items now
  # For neighbors, we only need metadata and annoy data, so umap_policy doesn't matter
  df_data, _, annoy_lookup, meta_dict = load_data(policy, policy)
  annoy_index = load_annoy_index(policy)

  if df_data is None or annoy_index is None:
    return html.Div("Error loading data"), html.Div(), []

  if not selected_track_id or selected_track_id not in meta_dict:
    return html.Div("No track selected."), html.Div(), []

  # --- OPTIMIZATION: Dictionary Lookup instead of .loc ---
  info = meta_dict[selected_track_id]
  
  now_playing = html.Div(
    style={
      "padding": "1rem 1.2rem",
      "borderRadius": "10px",
      "backgroundColor": "#f0f2f6",
      "marginBottom": "1rem",
      "color": "black",
    },
    children=[
      html.H3(f"🎧 Now Playing: {info['TrackName']}"),
      html.P(
        [
          html.B("Artist: "),
          info["ArtistName"],
          " | ",
          html.B("Album: "),
          info["AlbumName"],
          " | ",
          html.B("TrackID: "),
          html.Code(selected_track_id),
        ]
      ),
      html.A(
        "Search on YouTube",
        href=f"https://www.youtube.com/results?search_query={info['ArtistName']} - {info['TrackName']}",
        target="_blank",
        style={
            "display": "inline-block",
            "marginTop": "0.5rem",
            "fontSize": "0.9rem",
            "color": "#007bff",
            "textDecoration": "none",
        }
      ),
      html.Audio(
        id="main-audio-player",
        src=AUDIO_API_TEMPLATE.format(track_id=selected_track_id),
        controls=True,
        autoPlay=True,
        style={"width": "100%", "marginTop": "0.5rem"},
      ),
    ],
  )

  # --- Nearest Neighbors ---
  try:
    vector_id = info["annoy_id"]
  except KeyError:
    return now_playing, html.Div("No annoy_id."), []

  query_vector = annoy_index.get_item_vector(int(vector_id))
  nearest_int_ids, distances = annoy_index.get_nns_by_vector(
    query_vector, 6, include_distances=True
  )

  neighbor_rows = []
  neighbor_ids = []
  for n_int_id, dist in zip(nearest_int_ids, distances):
    neighbor_tid = annoy_lookup.get(n_int_id)
    
    if not neighbor_tid or neighbor_tid == selected_track_id:
      continue

    neighbor_ids.append(neighbor_tid)
    # --- OPTIMIZATION: Instant Dict Lookup ---
    n_info = meta_dict[neighbor_tid]

    neighbor_rows.append(
      html.Div(
        style={"borderBottom": "1px solid #eee", "padding": "0.6rem 0"},
        children=[
          html.Div(
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
            children=[
              html.Div(
                [
                  html.Strong(n_info["TrackName"]),
                  html.Div(
                    children=[
                        html.Span(f"{n_info['ArtistName']} | Album: {n_info['AlbumName']} | Dist: {dist:.4f}"),
                        html.A(
                            " SEARCH ON YOUTUBE",
                            href=f"https://www.youtube.com/results?search_query={n_info['ArtistName']} - {n_info['TrackName']}",
                            target="_blank",
                            title="Search on YouTube",
                            style={"textDecoration": "none", "marginLeft": "0.3rem", "color": "#007bff"}
                        )
                    ],
                    style={"fontSize": "0.85rem", "color": "#555"},
                  ),
                ]
              ),
              html.Button(
                "Explore Neighbor",
                id={"type": "neighbor-select", "index": neighbor_tid},
                type="button",
                title="Select this track",
                style={
                  "cursor": "pointer",
                  "background": "transparent",
                  "fontSize": "0.9rem",
                  "color": "#007bff",
                  "border": "1px solid #007bff",
                },
              ),
            ],
          ),
          html.Audio(
            src=AUDIO_API_TEMPLATE.format(track_id=neighbor_tid),
            controls=True,
            preload="none", 
            style={"width": "100%", "marginTop": "0.3rem"},
          ),
        ],
      )
    )

  return now_playing, html.Div(
    children=[html.H4("Nearest Neighbors"), html.Div(neighbor_rows)]
  ), neighbor_ids


@app.callback(
  Output("history-store", "data"),
  Output("journey-container", "children"),
  Input("selected-track-store", "data"),
  State("history-store", "data"),
  State("policy-dropdown", "value"),
)
def update_history(selected_track_id, history_data, policy):
  """
  Update history store and render journey list.
  """
  if not history_data:
    history_data = []

  # Don't update if no track selected
  if not selected_track_id:
    return dash.no_update, dash.no_update

  # Avoid adding duplicate if it's the same as the last one (e.g. page refresh)
  if history_data and history_data[-1] == selected_track_id:
      pass
  else:
      history_data.append(selected_track_id)

  # Limit history size if needed (e.g. last 50)
  if len(history_data) > 50:
      history_data = history_data[-50:]

  # Render the list (Reverse chronological order)
  df_data, _, _, meta_dict = load_data(policy, policy)
  
  if df_data is None:
      return history_data, []

  items = []
  # Iterate in reverse to show newest first
  for i, tid in enumerate(reversed(history_data)):
      if tid not in meta_dict:
          continue
          
      info = meta_dict[tid]
      items.append(
          html.Div(
              style={
                  "padding": "0.3rem 0",
                  "borderBottom": "1px solid #eee",
                  "fontSize": "0.85rem",
                  "display": "flex",
                  "justifyContent": "space-between",
                  "alignItems": "center"
              },
              children=[
                  html.Span(f"{len(history_data) - i}. {info['ArtistName']} - {info['TrackName']}", style={"marginRight": "0.5rem", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap", "flex": "1"}),
                  html.Button(
                      "↺",
                      id={"type": "history-select", "index": tid},
                      title="Replay this track",
                      style={
                          "cursor": "pointer",
                          "background": "transparent",
                          "border": "1px solid #ddd",
                          "borderRadius": "50%",
                          "width": "24px",
                          "height": "24px",
                          "display": "flex",
                          "alignItems": "center",
                          "justifyContent": "center",
                          "color": "#666",
                          "fontSize": "1rem"
                      }
                  )
              ]
          )
      )

  if not items:
      return history_data, html.Div("No history yet.", style={"color": "#999", "fontStyle": "italic"})

  return history_data, items


app.clientside_callback(
  """
  function(n_intervals, switch_values, neighbors) {
    if (!n_intervals || !switch_values || !switch_values.includes('enabled') || !neighbors || neighbors.length === 0) {
      return dash_clientside.no_update;
    }
    var audio = document.getElementById('main-audio-player');
    if (audio && audio.ended) {
      // Pick random neighbor
      var randomIndex = Math.floor(Math.random() * neighbors.length);
      var nextTrack = neighbors[randomIndex];
      return nextTrack;
    }
    return dash_clientside.no_update;
  }
  """,
  Output("auto-play-trigger", "data"),
  Input("audio-poller", "n_intervals"),
  State("auto-play-switch", "value"),
  State("current-neighbors-store", "data"),
)

if __name__ == "__main__":
  app.run(debug=True)
