import os
from functools import lru_cache

import annoy
import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State
import dash

# --- Constants ---
METADATA_CSV_FILE = "embeddings/id_metadata.csv"
TENSOR_DIRECTORY = "embeddings/embeddings/"
VECTOR_INDEX_DIR = "vector_index"
UMAP_CSV_FILE = "umap_data_mean.csv"

ANN_TEMPLATE = f"{VECTOR_INDEX_DIR}/annoy_index_{{pooling_policy}}.ann"
# Mapping UUIDs to Annoy integer IDs
VECTOR_ID_TO_KEY_TEMPLATE = (
  f"{VECTOR_INDEX_DIR}/annoy_int_index_to_uuid_{{pooling_policy}}.csv"
)
AUDIO_API_TEMPLATE = "https://staging-api.marisad.me/api/asset/track/{track_id}/hls"

POOLING_POLICY_DIM = {"mean": 1024, "mean+max": 2048}
DEFAULT_POLICY = "mean"


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
def load_data(policy: str):
  """
  Load data and return fast lookup structures.
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

  # 5. Load UMAP
  umap_df = None
  if os.path.exists(UMAP_CSV_FILE):
    umap_df = pd.read_csv(UMAP_CSV_FILE)

  return merged_df, umap_df, annoy_to_track_map, meta_dict

@lru_cache(maxsize=None)
def make_umap_figure(policy: str, sample_size: int = 5000):
  """Build a Plotly figure for the UMAP scatter for a given policy."""
  # Unpack 3 values now (we ignore the lookup map here)
  df_data, df_umap, _, _ = load_data(policy)
  
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
      ],
      style={"display": "flex", "alignItems": "center", "marginBottom": "1rem"},
    ),

    # Store for global selected track id
    dcc.Store(id="selected-track-store"),

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
            html.Label("Search by Track ID:"),
            dcc.Input(
              id="track-input",
              type="text",
              placeholder="Type TrackID...",
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
            html.H3("🗺️ 2D Map"),
            html.Div(
              "Click on a point to play the song! (Rendering sample for speed)",
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
  Output("umap-graph", "figure"),
  Input("policy-dropdown", "value"),
)
def on_policy_change(policy):
  """
  When policy changes:
   - Update UMAP figure only
  """
  fig = make_umap_figure(policy)
  return fig


@app.callback(
  Output("selected-track-store", "data"),
  Output("track-input", "value"),
  Input("umap-graph", "clickData"),
  Input("track-input", "value"),
  State("policy-dropdown", "value"),
  State("selected-track-store", "data"),
  prevent_initial_call=True,
)
def on_selection_change(clickData, track_input_value, policy, current_track_id):
  """
  Single callback responsible for BOTH:
   - updating selected-track-store.data
   - keeping track-input.value in sync
  """
  ctx = dash.callback_context
  if not ctx.triggered:
    raise dash.exceptions.PreventUpdate

  trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

  # Unpack 3 values (ignore lookup here)
  df_data, _, _, _ = load_data(policy)
  
  if df_data is None or df_data.empty:
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

  # Case 2: User typed in the input
  if trigger_id == "track-input":
    track_id = track_input_value
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
            [
              html.Strong(n_info["TrackName"]),
              html.Div(
                f"{n_info['ArtistName']} | Dist: {dist:.4f}",
                style={"fontSize": "0.85rem", "color": "#555"},
              ),
            ]
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
