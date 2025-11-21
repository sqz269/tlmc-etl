import os
import json
from functools import lru_cache

import annoy
import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State, ALL
import dash

# --- Constants ---
METADATA_CSV_FILE = "embeddings/id_metadata.csv"
VECTOR_INDEX_DIR = "vector_index"
UMAP_CSV_FILE_TEMPLATE = "umap_data_{pooling_policy}.csv"

ANN_TEMPLATE = f"{VECTOR_INDEX_DIR}/annoy_index_{{pooling_policy}}.ann"
# Mapping UUIDs to Annoy integer IDs
VECTOR_ID_TO_KEY_TEMPLATE = (
  f"{VECTOR_INDEX_DIR}/annoy_int_index_to_uuid_{{pooling_policy}}.csv"
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
  if os.path.exists(umap_file):
    umap_df = pd.read_csv(umap_file)

  return merged_df, umap_df, annoy_to_track_map, meta_dict

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


def make_umap_figure(policy: str, selected_track_id: str = None, sample_size: int = SAMPLE_SIZE, umap_policy: str = None):
  """
  Get base figure and add highlight trace for selected track.
  Args:
    policy: Pooling policy for Annoy index
    selected_track_id: Track ID to highlight
    sample_size: Number of points to sample
    umap_policy: Pooling policy for UMAP visualization (defaults to policy if None)
  """
  if umap_policy is None:
    umap_policy = policy
    
  # 1. Get cached base figure
  base_fig = get_base_umap_figure(policy, umap_policy, sample_size)
  
  # 2. Create a lightweight copy to avoid mutating the cached object
  # (layout and data are dicts/lists, so we need to be careful, 
  # but updating layout or adding traces usually works fine with a shallow copy 
  # IF we use the internal graph object methods which handle this, 
  # OR we can just construct a new Figure from the old one's dict)
  
  # Using a fresh Figure object wrapping the old one's data/layout is safest
  import plotly.graph_objects as go
  fig = go.Figure(base_fig)

  if not selected_track_id:
    return fig

  # 3. Find selected track coords - make sure we pass both policies explicitly
  _, df_umap, _, _ = load_data(policy, umap_policy)
  if df_umap is None:
    return fig

  # Assuming df_umap has TrackID column
  row = df_umap[df_umap["TrackID"] == selected_track_id]
  if row.empty:
    # Track not found in this UMAP visualization, skip highlighting
    # This can happen if different UMAP files have different tracks
    return fig
  
  # 4. Add highlight trace
  # We use a separate Scatter trace
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

app.title = "Music Embedding Explorer (Dash)"

app.layout = html.Div(
  style={"fontFamily": "system-ui, -apple-system, BlinkMacSystemFont, sans-serif"},
  children=[
    html.H2("🎵 Music Embedding Explorer", style={"marginBottom": "0.5rem"}),
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

    # Now Playing section
    html.Div(id="now-playing", style={"marginBottom": "1.5rem"}),

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
            html.Div(id="search-results", style={"marginBottom": "1rem"}),
            
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
            html.Div(id="neighbors-container"),
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
            dcc.Graph(
              id="umap-graph",
              figure=make_umap_figure(DEFAULT_POLICY),
              style={"height": "650px"},
              config={"displayModeBar": False},
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
  Output("map-title", "children"),
  Output("map-subtitle", "children"),
  Input("policy-dropdown", "value"),
  Input("umap-policy-dropdown", "value"),
  Input("sample-size-store", "data"),
)
def update_map_labels(policy, umap_policy, sample_size):
  """Update map title and subtitle based on policy and sample size."""
  title = f"🗺️ 2D Map (Search: {policy}, UMAP: {umap_policy}, Sample: {sample_size}) (Click to Play)"
  subtitle = "NOTE: Different UMAP policies may produce different visualizations interms of genre placement in the space."
  return title, subtitle


@app.callback(
  Output("umap-graph", "figure"),
  Input("policy-dropdown", "value"),
  Input("umap-policy-dropdown", "value"),
  Input("selected-track-store", "data"),
  Input("sample-size-store", "data"),
)
def update_map(policy, umap_policy, selected_track_id, sample_size):
  """
  Update UMAP figure when policy, track selection, or sample size changes.
  """
  if not sample_size or sample_size <= 0:
    sample_size = SAMPLE_SIZE
  return make_umap_figure(policy, selected_track_id, sample_size, umap_policy)


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
  State("policy-dropdown", "value"),
  State("selected-track-store", "data"),
  prevent_initial_call=True,
)
def on_selection_change(clickData, track_id_input_value, search_clicks, neighbor_clicks, policy, current_track_id):
  """
  Single callback responsible for updating selected-track-store and input.
  """
  ctx = dash.callback_context
  if not ctx.triggered:
    raise dash.exceptions.PreventUpdate

  trigger_prop_id = ctx.triggered[0]["prop_id"]
  trigger_id = trigger_prop_id.split(".")[0]

  # Unpack 3 values (ignore lookup here)
  # For selection validation, we only need metadata, so umap_policy doesn't matter
  df_data, _, _, _ = load_data(policy, policy)
  
  if df_data is None or df_data.empty:
    raise dash.exceptions.PreventUpdate

  # Helper to handle pattern-matched triggers (search results or neighbors)
  if "search-result" in trigger_id or "neighbor-select" in trigger_id:
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
  Input("selected-track-store", "data"),
  State("policy-dropdown", "value"),
)
def update_now_playing_and_neighbors(selected_track_id, policy):
  # Unpack 4 items now
  df_data, _, annoy_lookup, meta_dict = load_data(policy)
  annoy_index = load_annoy_index(policy)

  if df_data is None or annoy_index is None:
    return html.Div("Error loading data"), html.Div()

  if not selected_track_id or selected_track_id not in meta_dict:
    return html.Div("No track selected."), html.Div()

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
    return now_playing, html.Div("No annoy_id.")

  query_vector = annoy_index.get_item_vector(int(vector_id))
  nearest_int_ids, distances = annoy_index.get_nns_by_vector(
    query_vector, 6, include_distances=True
  )

  neighbor_rows = []
  for n_int_id, dist in zip(nearest_int_ids, distances):
    neighbor_tid = annoy_lookup.get(n_int_id)
    
    if not neighbor_tid or neighbor_tid == selected_track_id:
      continue

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
                        html.Span(f"{n_info['ArtistName']} | Dist: {dist:.4f}"),
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
  )

if __name__ == "__main__":
  app.run(debug=True)
