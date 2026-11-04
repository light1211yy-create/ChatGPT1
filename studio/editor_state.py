"""Session-only edit snapshots. Never rebase an unsaved edit automatically."""
import streamlit as st


def capture_editor_inputs():
    """Keep submitted widget values before Streamlit removes hidden widgets."""
    for state in st.session_state.get("_makase_editors", {}).values():
        for field in state["fields"]:
            key = f"{state['key']}_{field}"
            if key in st.session_state:
                state["draft"][field] = st.session_state[key]


class Editor:
    def __init__(self, kind, current, labels):
        registry = st.session_state.setdefault("_makase_editors", {})
        identity = f"{kind}_{current['id']}"
        self.state = registry.setdefault(identity, {"record": None, "epoch": 0, "draft": {}, "fields": [], "compare": False})
        if self.state["record"] is None:
            self.state["record"] = dict(current)
        self.record = self.state["record"]
        self.key = f"edit_{identity}_{self.state['epoch']}"
        self.state["key"] = self.key
        self.version = self.record["version"]
        self.labels = labels

    def widget_key(self, field):
        if field not in self.state["fields"]:
            self.state["fields"].append(field)
        return f"{self.key}_{field}"

    def value(self, field, default=""):
        return self.state["draft"].get(field, self.record.get(field, default))

    def reset(self, current=None):
        self.state.update(record=dict(current) if current else None, epoch=self.state["epoch"] + 1,
                          draft={}, fields=[], compare=False)

    def show_conflict(self, current):
        if self.version == current["version"]:
            return
        st.warning("別の画面で更新されています。この編集は保存できません。編集中の内容は保持しています。最新データと比較して確認してください。")
        if st.button("最新データを再読み込みして比較（編集を保持）", key=f"compare_{self.key}"):
            self.state["compare"] = True
            st.rerun()
        if self.state["compare"]:
            st.dataframe([{"項目": label, "編集開始時": str(self.record.get(field, "")),
                           "編集中の内容": str(self.value(field)), "最新の保存値": str(current.get(field, ""))}
                          for field, label in self.labels.items()], hide_index=True, width="stretch")
        if st.button("編集内容を破棄して最新データを読み込む", key=f"discard_{self.key}"):
            self.reset(current)
            st.rerun()


def retained_editor(kind, identifier):
    return st.session_state.get("_makase_editors", {}).get(f"{kind}_{identifier}")
