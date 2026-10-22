import streamlit as st
import json
import random
import requests
from pathlib import Path
from typing import List, Dict, Set

# 優先讀取 Streamlit Secrets，若無則使用寫死的預設金鑰
API_KEY = st.secrets.get("GEMINI_API_KEY", "AQ.Ab8RN6IoTzjpp7WJnQzCxBbGKXaJMS-9wg2Q64pZki5xnM2ZrA")
MODEL_NAME = "gemini-flash-latest"

# =====================================================================
# 1. AI 盲點拆解請求函式 (使用原生 requests，完美相容 AQ 金鑰)
# =====================================================================
def generate_ai_explanation(question_data: dict, user_ans: list, correct_ans: list) -> str:
    options_str = "\n".join([f"{k}: {v}" for k, v in question_data.get("options_zh", question_data["options"]).items()])
    
    prompt = f"""你是一位精通台灣長宏 PMP 教材的專案管理教練。學員剛答錯了一道題目。

【題目資訊】
- 長宏章節：{question_data['chapter_tag']}
- 核心觀念：{question_data['concept_tag']} ({question_data['approach']})
- 英文題幹：{question_data['question_text']}
- 中文題幹：{question_data.get('question_text_zh', '')}
- 選項內容：
{options_str}

【作答狀況】
- 正確答案：{', '.join(correct_ans)}
- 學員誤選：{', '.join(user_ans)}

請完全使用繁體中文（台灣長宏標準專案管理用語，嚴禁大陸用語），以條列式提供精煉的診斷：
1. 🎯 **盲點拆解**：一針見血指出為什麼學員誤選的「{', '.join(user_ans)}」不符合 PMI 思維或掉入什麼情境陷阱。
2. ✅ **正解邏輯**：說明題幹中的哪個關鍵線索指向正確答案「{', '.join(correct_ans)}」，以及背後對應的長宏/PMBOK 流程原則。
3. 💡 **長宏考場秒殺口訣**：給出一句好記的核心判斷法則，下次看到類似情境能 3 秒選出正解。
"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"
    
    # 完美重現你之前成功的 cURL Header
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": API_KEY
    }
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        return f"⚠️ API 發生錯誤 ({response.status_code})：{response.text}"
    except Exception as e:
        return f"⚠️ 連線失敗，無法載入解析。錯誤：{e}"

# =====================================================================
# 2. 適性化抽題引擎 (PMP Adaptive Engine)
# =====================================================================
class PMPAdaptiveEngine:
    def __init__(self, question_bank_json: str):
        with open(question_bank_json, "r", encoding="utf-8") as f:
            raw_pool = json.load(f)
        translated_pool = [q for q in raw_pool if "question_text_zh" in q and "options_zh" in q]
        self.full_pool = translated_pool if len(translated_pool) >= 20 else raw_pool
            
        self.q_dict = {q["question_id"]: q for q in self.full_pool}
        self.concepts_index = self._build_concept_index()
        
        self.current_round = 0
        self.consecutive_perfect = 0
        self.used_qids: Set[str] = set()
        self.tested_concepts: Set[str] = set()
        self.weak_concepts: Dict[str, int] = {}

    def _build_concept_index(self) -> Dict[str, List[str]]:
        index = {}
        for q in self.full_pool:
            c_tag = q.get("concept_tag", "未分類")
            if c_tag not in index:
                index[c_tag] = []
            index[c_tag].append(q["question_id"])
        return index

    def generate_next_round(self, questions_per_round: int = 10) -> dict:
        if self.current_round >= 10:
            return {"status": "completed", "message": "🎯 恭喜！已完成 10 輪複習任務！"}
        if self.consecutive_perfect >= 2:
            return {"status": "completed", "message": "🏆 恭喜！連續兩輪全對，提早通關！"}

        self.current_round += 1
        selected_qids = set()

        if self.current_round == 1:
            available_qids = [q["question_id"] for q in self.full_pool if q["question_id"] not in self.used_qids]
            selected_qids = set(random.sample(available_qids, min(questions_per_round, len(available_qids))))
        else:
            weak_quota = int(questions_per_round * 0.6)
            sorted_weak = sorted(self.weak_concepts.keys(), key=lambda k: self.weak_concepts[k], reverse=True)
            
            for concept in sorted_weak:
                if len(selected_qids) >= weak_quota: break
                available_for_concept = [qid for qid in self.concepts_index[concept] if qid not in self.used_qids and qid not in selected_qids]
                if available_for_concept:
                    selected_qids.update(random.sample(available_for_concept, min(2, len(available_for_concept), weak_quota - len(selected_qids))))

            remaining_quota = questions_per_round - len(selected_qids)
            available_new = [q["question_id"] for q in self.full_pool if q["question_id"] not in self.used_qids and q["question_id"] not in selected_qids and q.get("concept_tag") not in self.tested_concepts]
            
            if len(available_new) >= remaining_quota:
                selected_qids.update(random.sample(available_new, remaining_quota))
            else:
                selected_qids.update(available_new)
                still_needed = questions_per_round - len(selected_qids)
                absolute_remains = [q["question_id"] for q in self.full_pool if q["question_id"] not in self.used_qids and q["question_id"] not in selected_qids]
                selected_qids.update(random.sample(absolute_remains, min(still_needed, len(absolute_remains))))

        self.used_qids.update(selected_qids)
        return {"status": "ongoing", "round": self.current_round, "questions": [self.q_dict[qid] for qid in selected_qids]}

    def submit_answers(self, user_answers: Dict[str, List[str]]) -> dict:
        round_score = 0
        wrong_questions = []

        for qid, user_ans in user_answers.items():
            q_data = self.q_dict[qid]
            correct_ans = sorted(q_data["correct_answers"])
            user_ans = sorted(user_ans)
            concept = q_data.get("concept_tag", "未分類")
            self.tested_concepts.add(concept)

            if user_ans == correct_ans:
                round_score += 1
                if concept in self.weak_concepts:
                    self.weak_concepts[concept] -= 1
                    if self.weak_concepts[concept] <= 0:
                        del self.weak_concepts[concept]
            else:
                self.weak_concepts[concept] = self.weak_concepts.get(concept, 0) + 1
                wrong_questions.append({
                    "question": q_data,
                    "user_ans": user_ans,
                    "correct_ans": correct_ans
                })

        if round_score == len(user_answers):
            self.consecutive_perfect += 1
        else:
            self.consecutive_perfect = 0

        return {"round_score": round_score, "wrong_questions": wrong_questions}

# =====================================================================
# 3. Streamlit 網頁應用程式介面
# =====================================================================
st.set_page_config(page_title="PMP 適性化刷題系統", page_icon="🎯", layout="centered")

if "engine" not in st.session_state:
    bank_file = "pmp_1300_bilingual_pro.json" if Path("pmp_1300_bilingual_pro.json").exists() else "pmp_1300_bilingual.json"
    try:
        st.session_state.engine = PMPAdaptiveEngine(bank_file)
        st.session_state.bank_file = bank_file
    except Exception as e:
        st.error(f"無法載入題庫，請確認題庫檔案是否存在。錯誤: {e}")
        st.stop()
        
    st.session_state.current_view = "quiz"
    st.session_state.round_data = st.session_state.engine.generate_next_round()
    st.session_state.current_q_index = 0
    st.session_state.user_answers = {}
    st.session_state.ai_explanations = {}

if st.session_state.round_data["status"] == "completed":
    st.success(st.session_state.round_data["message"])
    st.balloons()
    if st.button("重新開始全新測驗"):
        st.session_state.clear()
        st.rerun()
    st.stop()

questions = st.session_state.round_data["questions"]
total_q = len(questions)
current_idx = st.session_state.current_q_index
q_data = questions[current_idx] if current_idx < total_q else None

# === 視圖 A：測驗畫面 ===
if st.session_state.current_view == "quiz":
    st.markdown(f"### 🎯 Round {st.session_state.engine.current_round} / 10")
    st.progress((current_idx) / total_q, text=f"Question {current_idx + 1} of {total_q} （題庫：{st.session_state.bank_file}）")
    
    st.markdown("---")
    st.markdown(f"**{q_data.get('question_text_zh', q_data['question_text'])}**")
    st.caption(f"*{q_data['question_text']}*")
    
    req_selections = q_data.get("required_selections", 1)
    zh_opts = q_data.get("options_zh", {})
    options_display = {
        k: f"{k}. {zh_opts.get(k, q_data['options'].get(k))} \n\n*{q_data['options'].get(k)}*" 
        for k in q_data['options'].keys()
    }
    
    if req_selections == 1:
        selected = st.radio(
            "請選擇 1 個答案：", 
            options=list(options_display.keys()), 
            format_func=lambda x: options_display[x], 
            index=None, 
            key=f"q_{q_data['question_id']}"
        )
        current_ans = [selected] if selected else []
    else:
        st.warning(f"📌 本題為多選題，請精確勾選 {req_selections} 個答案。")
        selected = st.multiselect(
            "請選擇答案：", 
            options=list(options_display.keys()), 
            format_func=lambda x: options_display[x], 
            max_selections=req_selections, 
            key=f"q_{q_data['question_id']}"
        )
        current_ans = selected

    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col3:
        if current_idx < total_q - 1:
            if st.button("下一題 ⏭️", use_container_width=True, disabled=len(current_ans) != req_selections):
                st.session_state.user_answers[q_data["question_id"]] = current_ans
                st.session_state.current_q_index += 1
                st.rerun()
        else:
            if st.button("完成作答 ✅", use_container_width=True, type="primary", disabled=len(current_ans) != req_selections):
                st.session_state.user_answers[q_data["question_id"]] = current_ans
                st.session_state.analysis_result = st.session_state.engine.submit_answers(st.session_state.user_answers)
                st.session_state.current_view = "analysis"
                st.rerun()

# === 視圖 B：分析與學習畫面 ===
elif st.session_state.current_view == "analysis":
    res = st.session_state.analysis_result
    score = res["round_score"]
    
    st.markdown(f"## 📊 第 {st.session_state.engine.current_round} 輪診斷報告")
    st.success(f"**本輪得分：{score} / {total_q}**")
    
    if score == total_q:
        st.balloons()
        st.info("太棒了！本輪全對，繼續保持以達成提早通關！")
    else:
        st.error(f"有 {len(res['wrong_questions'])} 題答錯，請複習以下盲點觀念：")
        
        for wq in res['wrong_questions']:
            q = wq["question"]
            qid = q["question_id"]
            zh_opts = q.get("options_zh", q["options"])
            
            with st.expander(f"❌ 答錯觀念：{q['concept_tag']} (所屬章節：{q['chapter_tag']})"):
                st.markdown(f"**題目：** {q.get('question_text_zh', q['question_text'])}")
                st.caption(f"*{q['question_text']}*")
                st.markdown(f"**你的答案：** `{', '.join(wq['user_ans'])}` ｜ **正確答案：** `{', '.join(wq['correct_ans'])}`")
                
                for k, v in zh_opts.items():
                    prefix = "✅" if k in wq['correct_ans'] else ("❌" if k in wq['user_ans'] else "⬜")
                    st.write(f"{prefix} **{k}**: {v}")
                
                st.markdown("---")
                
                if qid not in st.session_state.ai_explanations:
                    if st.button(f"🤖 召喚 AI 盲點拆解", key=f"btn_{qid}"):
                        with st.spinner("AI 教練正在根據長宏教材診斷您的盲點..."):
                            explanation = generate_ai_explanation(q, wq['user_ans'], wq['correct_ans'])
                            st.session_state.ai_explanations[qid] = explanation
                            st.rerun()
                else:
                    st.info(st.session_state.ai_explanations[qid])

    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col3:
        if st.button("進行下一輪測試 🚀", use_container_width=True, type="primary"):
            st.session_state.current_view = "quiz"
            st.session_state.round_data = st.session_state.engine.generate_next_round()
            st.session_state.current_q_index = 0
            st.session_state.user_answers = {}
            st.session_state.ai_explanations = {}
            st.rerun()
