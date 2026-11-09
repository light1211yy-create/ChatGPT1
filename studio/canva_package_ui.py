"""One-click offline content handoff for the user's existing free Canva template."""
import streamlit as st

from studio.canva_package import CanvaPackageError, build_canva_package


def canva_package_panel(store, theme_id, facilities):
    with st.expander("Canva用7ページ制作パック（Phase 4）", expanded=False):
        st.write("投稿テーマと選んだ5施設から、既存Canvaテンプレートへ貼り付ける"
                 "7ページ分の文章・素材参照・確認リストをZIPで作成します。")
        st.caption("外部APIへの通信・Geminiへの送信・DB保存・画像ダウンロードはしません。"
                   "Canvaの既存デザインは変更されません。")
        eligible = [f for f in facilities if f["candidate_status"] != "見送り"]
        if len(eligible) < 5:
            st.info("制作パックには見送り以外の5施設が必要です。先にAI施設リサーチで候補を登録するか、手動で追加してください。")
            return
        mapping = {f["id"]: f for f in eligible}
        priority_ids = [f["id"] for f in eligible if f["candidate_status"] == "優先候補"]
        order = priority_ids + [f["id"] for f in eligible if f["id"] not in priority_ids]
        selected = st.multiselect(
            "紹介する施設5件（表示順）", options=order, default=order[:5],
            format_func=lambda fid: mapping[fid]["name"],
            key=f"canva_selected_facilities_{theme_id}",
        )
        if len(selected) != 5:
            st.info("異なる5施設を選択すると制作パックをダウンロードできます。")
            return
        try:
            data, filename, stats = build_canva_package(store, theme_id, selected)
        except (CanvaPackageError, ValueError) as error:
            st.error(str(error))
            return
        st.write(f"7ページ（表紙・施設5件・保存案内）／施設写真の候補リンク："
                 f"{stats['photo_source_slots']}/10枠")
        if stats["missing_photo_slots"]:
            st.info(f"写真リンクが不足している箇所：{stats['missing_photo_slots']}枠。"
                    "未許諾写真は含めず空欄にしています。")
        st.caption("内容は未公開の制作下書きです。価格・所在地などの事実確認、商用SNS利用・編集に関する写真の許諾確認をしてから制作してください。"
                   "写真データやMP4、Canva編集済みファイルは含まれません。")
        st.download_button(
            "Canva用7ページ制作パック（ZIP）を保存",
            data=data, file_name=filename, mime="application/zip",
            key=f"canva_package_download_{theme_id}",
        )
