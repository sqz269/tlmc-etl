import streamlit as st
import annoy
import pandas as pd
import os
import plotly.express as px

# --- Constants ---
METADATA_CSV_FILE = "embeddings/id_metadata.csv"
TENSOR_DIRECTORY = "embeddings/embeddings/"
VECTOR_INDEX_DIR = "vector_index"
UMAP_CSV_FILE = "umap_data_mean.csv" 

ANN_TEMPLATE = f"{VECTOR_INDEX_DIR}/annoy_index_{{pooling_policy}}.ann"
# ADDED: This file is required to map UUIDs to Annoy Integers
VECTOR_ID_TO_KEY_TEMPLATE = f"{VECTOR_INDEX_DIR}/annoy_int_index_to_uuid_{{pooling_policy}}.csv"
AUDIO_API_TEMPLATE = "https://staging-api.marisad.me/api/asset/track/{track_id}/hls"

POOLING_POLICY_DIM = {"mean": 1024, "mean+max": 2048}

# --- Page Config ---
st.set_page_config(page_title="Music Embedding Explorer", layout="wide")

if 'selected_track_id' not in st.session_state:
  st.session_state['selected_track_id'] = None

def update_track(track_id):
  st.session_state['selected_track_id'] = track_id

# --- Caching Functions ---
@st.cache_resource
def load_annoy_index(choice):
  ann_index_path = ANN_TEMPLATE.format(pooling_policy=choice)
  if not os.path.exists(ann_index_path): return None
  embedding_dim = POOLING_POLICY_DIM[choice]
  annoy_index = annoy.AnnoyIndex(embedding_dim, "angular")
  annoy_index.load(ann_index_path)
  return annoy_index

@st.cache_data
def load_data(choice):
  """
  Loads metadata AND the Integer-to-UUID mapping for the specific policy.
  Returns a merged DataFrame where we can look up by TrackID but also get the Annoy ID.
  """
  map_path = VECTOR_ID_TO_KEY_TEMPLATE.format(pooling_policy=choice)
  
  if not os.path.exists(map_path):
    return None, None

  # 1. Load the Mapping (The index of this DF is the Annoy Integer ID)
  # We reset_index so the Annoy Integer becomes a standard column named 'annoy_id'
  id_map_df = pd.read_csv(map_path, index_col=0)
  id_map_df.index.name = 'annoy_id'
  id_map_df = id_map_df.reset_index() # Now columns are ['annoy_id', 'TrackID']

  # 2. Load the Metadata
  meta_df = pd.read_csv(METADATA_CSV_FILE)

  # 3. Merge them
  # This ensures we only keep tracks that actually exist in the Annoy Index
  # and we attach the correct 'annoy_id' to them.
  merged_df = pd.merge(id_map_df, meta_df, on="TrackID", how="inner")
  
  # 4. Set index to TrackID for easy searching, but keep annoy_id as a column
  merged_df = merged_df.set_index("TrackID")
  
  # 5. Also load UMAP if available
  umap_df = None
  if os.path.exists(UMAP_CSV_FILE):
    umap_df = pd.read_csv(UMAP_CSV_FILE)

  return merged_df, umap_df

# --- Main App ---
def main():
  st.title("🎵 Music Embedding Explorer")

  # Sidebar Configuration
  with st.sidebar:
    policy = st.selectbox("Search Policy", list(POOLING_POLICY_DIM.keys()))
    
  # Load Data based on Policy
  df_data, df_umap = load_data(policy)
  annoy_index = load_annoy_index(policy)

  if df_data is None or annoy_index is None:
    st.error(f"Could not load index or mapping files for policy: {policy}")
    return

  # --- TOP SECTION: PLAYER ---
  current_id = st.session_state['selected_track_id']
  
  if current_id and current_id in df_data.index:
    track_info = df_data.loc[current_id]
    st.markdown(f"""
    <div style="padding: 20px; border-radius: 10px; background-color: #f0f2f6; margin-bottom: 20px; color: black;">
      <h3>🎧 Now Playing: {track_info['TrackName']}</h3>
      <p><b>Artist:</b> {track_info['ArtistName']} | <b>Album:</b> {track_info['AlbumName']} | <b>TrackID:</b> <code>{current_id}</code></p>
    </div>
    """, unsafe_allow_html=True)
    st.audio(AUDIO_API_TEMPLATE.format(track_id=current_id), format='audio/mp4')
  elif current_id:
    st.warning("Track ID not found in current index.")

  # --- TABS ---
  tab_search, tab_map = st.tabs(["🔍 Search & Similarity", "🗺️ 2D Map"])

  # --- TAB 1: SEARCH ---
  with tab_search:
    col1, col2 = st.columns([3, 1])
    with col1:
      search_input = st.text_input("Search by Track ID", value=current_id if current_id else "")
      if search_input and search_input != current_id:
        update_track(search_input)
        st.rerun()

    st.subheader("Nearest Neighbors")
    if current_id and current_id in df_data.index:
      
      # --- FIX IS HERE ---
      # We get the specific integer ID for Annoy from our merged column
      vector_id = df_data.loc[current_id]['annoy_id']
      
      # Query Annoy
      query_vector = annoy_index.get_item_vector(vector_id)
      nearest_int_ids, distances = annoy_index.get_nns_by_vector(query_vector, 6, include_distances=True)

      results = []
      for n_int_id, distance in zip(nearest_int_ids, distances):
        # Reverse lookup: Find the TrackID that has this annoy_id
        # Since 'annoy_id' is a column, we can query it.
        # (This is fast enough for 5 items, but could be optimized if needed)
        match = df_data[df_data['annoy_id'] == n_int_id]
        
        if match.empty: continue
        
        neighbor_key = match.index[0] # The TrackID
        n_info = match.iloc[0]

        if neighbor_key == current_id: continue
          
        results.append({
          "TrackID": neighbor_key,
          "Track Name": n_info['TrackName'],
          "Artist": n_info['ArtistName'],
          "Distance": f"{distance:.4f}",
          "Play": AUDIO_API_TEMPLATE.format(track_id=neighbor_key)
        })

      # Display Results
      for res in results:
        with st.container():
          r_col1, r_col2, r_col3 = st.columns([3, 2, 1])
          with r_col1:
            st.markdown(f"**{res['Track Name']}**")
            st.caption(res['Artist'])
          with r_col2:
            st.audio(res['Play'], format='audio/mp4')
          with r_col3:
            st.markdown(f"`Dist: {res['Distance']}`")
            if st.button("Select", key=res['TrackID']):
              update_track(res['TrackID'])
              st.rerun()

  # --- TAB 2: INTERACTIVE GRAPH ---
  with tab_map:
    if df_umap is None:
      st.warning(f"Please run the preprocessing script to generate '{UMAP_CSV_FILE}' first.")
    else:
      st.caption("Click on a point to play the song! (Rendering 5k sample points for speed)")
      df_plot = df_umap.sample(min(5000, len(df_umap)), random_state=42)
      
      fig = px.scatter(
        df_plot, x="x", y="y", color="ArtistName",
        hover_data=["TrackName", "ArtistName", "TrackID"],
        custom_data=["TrackID"], 
        title="Music Embedding Landscape (UMAP)",
        render_mode="webgl"
      )
      fig.update_layout(clickmode='event+select', height=600, xaxis_visible=False, yaxis_visible=False, showlegend=False)
      fig.update_traces(marker=dict(size=5, opacity=0.8))

      event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points")
      
      if len(event['selection']['points']) > 0:
        clicked_point = event['selection']['points'][0]
        clicked_id = clicked_point['customdata'][0]
        if clicked_id != st.session_state['selected_track_id']:
          update_track(clicked_id)
          st.rerun()

if __name__ == "__main__":
  main()