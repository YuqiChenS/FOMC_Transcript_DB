"""FOMC topic dashboard

Pick a year, see the topic mix of each meeting in it, and open the pyLDAvis
topic map on the selected meeting's main topic.

Run from the project root:
    streamlit run app.py
"""
import altair as alt
import pandas as pd
import streamlit as st

from src.modeling.LDA import MODEL_DIR, TOPIC_LABELS
from src.storage.mongo_client import MongoDatabase

# one color per topic id (colorblind-checked palette, always in this order)
TOPIC_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

st.set_page_config(page_title="FOMC Topics", layout="wide")


@st.cache_resource
def get_db():
    return MongoDatabase()


@st.cache_data
def load_run():
    """Newest LDA run from lda_metadata (model file, vis file, top words)"""
    return get_db().lda_metadata.find_one(sort=[("built_at", -1)], projection={"_id": 0})


@st.cache_data
def load_meetings(model_file):
    """One row per meeting with its topic weights, for the given model

    Args:
        model_file (str): Only meetings whose topics came from this model

    Return:
        DataFrame: meeting_end, date, year, dominant_topic, weight,
            minutes_url, and a topic_<id> column per topic
    """
    db = get_db()
    urls = {d["meeting_end"]: d.get("minutes_url")
            for d in db.metadata.find({}, {"meeting_end": 1, "minutes_url": 1})}

    rows = []
    for doc in db.minutes_clean.find({"model_file": model_file}, {"tokens": 0}):
        row = {
            "meeting_end": doc["meeting_end"],
            "date": pd.to_datetime(doc["meeting_end"], format="%Y%m%d"),
            "year": int(doc["meeting_end"][:4]),
            "dominant_topic": doc["dominant_topic"],
            "weight": doc["dominant_topic_weight"],
            "minutes_url": urls.get(doc["meeting_end"]),
        }
        for t in doc["topic_distribution"]:
            row[f"topic_{t['topic_id']}"] = t["weight"]
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


@st.cache_data
def load_vis_html(vis_file):
    """Read the pyLDAvis HTML saved next to the model, None if it's missing"""
    if not vis_file:
        return None
    path = MODEL_DIR / vis_file
    return path.read_text() if path.exists() else None


def focus_topic(vis_html, topic_id):
    """Make the pyLDAvis map open with one topic selected

    pyLDAvis reads "#topic=k&lambda=1&term=" from the page URL when it loads,
    and it numbers topics from 1, so our topic 0 is its topic 1. The map is
    about 1200px wide, so it's also shrunk a bit to fit the page.
    """
    set_hash = f'<script>location.hash = "topic={topic_id + 1}&lambda=1&term=";</script>'
    shrink = "<style>body { zoom: 0.75; }</style>"
    return set_hash + shrink + vis_html


# ---------- load ----------
run = load_run()
if run is None:
    st.error("No LDA run found in fomc_lda_metadata. Run the pipeline first.")
    st.stop()

model_file = run["model_file"]
num_topics = run["topic_number"]
labels = TOPIC_LABELS.get(model_file, {})
names = [labels.get(i, f"Topic {i}").replace("_", " ") for i in range(num_topics)]
topic_cols = [f"topic_{i}" for i in range(num_topics)]

meetings = load_meetings(model_file)
if meetings.empty:
    st.error(f"No meetings have topics from {model_file}. Run the lda stage first.")
    st.stop()

# ---------- sidebar ----------
years = sorted(meetings["year"].unique(), reverse=True)
year = st.sidebar.selectbox("Year", years)

st.sidebar.subheader("Topics")
for topic in run["results"]:
    words = ", ".join(t["word"].replace("_", " ") for t in topic["terms"][:6])
    st.sidebar.markdown(f"**{names[topic['topic_id']]}**  \n{words}")

# ---------- header ----------
st.title("FOMC Minutes: Topics Over Time")
st.caption(f"Model {model_file} · {num_topics} topics · "
           f"average coherence {run.get('average_coherence', 'n/a')}")
if not labels:
    st.info(f"No labels for {model_file} yet. Add them to TOPIC_LABELS in src/modeling/LDA.py.")

# ---------- topic share by year ----------
share = (meetings.groupby("year")[topic_cols].mean().reset_index()
         .melt("year", var_name="col", value_name="share"))
share["topic_id"] = share["col"].str.removeprefix("topic_").astype(int)
share["topic"] = share["topic_id"].map(dict(enumerate(names)))

share_chart = alt.Chart(share).mark_bar().encode(
    x=alt.X("year:O", title=None),
    y=alt.Y("share:Q", stack="normalize", title="Share of meeting text",
            axis=alt.Axis(format="%")),
    color=alt.Color("topic:N", title=None,
                    scale=alt.Scale(domain=names, range=TOPIC_COLORS[:num_topics]),
                    legend=alt.Legend(orient="top")),
    order=alt.Order("topic_id:Q"),
    opacity=alt.condition(alt.datum.year == int(year), alt.value(1.0), alt.value(0.45)),
    tooltip=[alt.Tooltip("year:O", title="Year"), alt.Tooltip("topic:N", title="Topic"),
             alt.Tooltip("share:Q", title="Share", format=".0%")],
).properties(height=280)

st.subheader("Topic share by year")
st.altair_chart(share_chart, width="stretch")
with st.expander("Show as table"):
    st.dataframe(share.pivot(index="year", columns="topic", values="share")[names]
                 .style.format("{:.0%}"))

# ---------- meetings in the selected year ----------
in_year = meetings[meetings["year"] == year].reset_index(drop=True)

st.subheader(f"Meetings in {year}")
st.caption("Click a row to see that meeting's topic mix and topic map below.")
table = pd.DataFrame({
    "Date": in_year["date"].dt.strftime("%b %d, %Y"),
    "Main topic": in_year["dominant_topic"].map(dict(enumerate(names))),
    "Main topic weight": in_year["weight"],
    "Minutes": in_year["minutes_url"],
})
event = st.dataframe(
    table,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Main topic weight": st.column_config.ProgressColumn(
            format="%.2f", min_value=0.0, max_value=1.0),
        "Minutes": st.column_config.LinkColumn(display_text="federalreserve.gov"),
    },
)

selected_rows = event.selection.rows
meeting = in_year.iloc[selected_rows[0] if selected_rows else 0]

# ---------- selected meeting ----------
st.subheader(f"{meeting['date']:%B %d, %Y} meeting")

mix = pd.DataFrame({
    "topic_id": range(num_topics),
    "topic": names,
    "weight": [meeting[c] for c in topic_cols],
})
mix_chart = alt.Chart(mix).mark_bar(cornerRadiusEnd=4).encode(
    x=alt.X("weight:Q", title="Topic weight", scale=alt.Scale(domain=[0, 1]),
            axis=alt.Axis(format="%")),
    y=alt.Y("topic:N", title=None, sort=names, axis=alt.Axis(labelLimit=250)),
    color=alt.Color("topic:N", legend=None,
                    scale=alt.Scale(domain=names, range=TOPIC_COLORS[:num_topics])),
    tooltip=[alt.Tooltip("topic:N", title="Topic"),
             alt.Tooltip("weight:Q", title="Weight", format=".0%")],
).properties(height=40 * num_topics)
st.altair_chart(mix_chart, width="stretch")

if meeting["minutes_url"]:
    st.link_button("Read these minutes on federalreserve.gov", meeting["minutes_url"])

st.subheader("Topic map")
vis_html = load_vis_html(run.get("vis_file"))
if vis_html is None:
    st.info("No pyLDAvis file saved for this model.")
else:
    main_topic = int(meeting["dominant_topic"])
    # our own file from training, so it's fine to embed as-is
    st.iframe(focus_topic(vis_html, main_topic), height=680)
