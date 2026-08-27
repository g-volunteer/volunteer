import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime
import io
import re

# --- 1. 기본 설정 및 DB 초기화 ---
st.set_page_config(
    page_title="임직원 봉사활동 신청 시스템",
    page_icon="🤝",
    layout="wide"
)

# 환경변수 GUC_APP_DATA 또는 로컬 경로에 DB 저장
data_dir = os.environ.get("GUC_APP_DATA", ".")
if not os.path.exists(data_dir):
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        data_dir = "."

DB_NAME = os.path.join(data_dir, "volunteer_system.db")

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    c = conn.cursor()
    
    # 1. activities 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            deadline TEXT,
            location TEXT NOT NULL,
            hours REAL NOT NULL,
            max_capacity INTEGER NOT NULL,
            description TEXT,
            status TEXT DEFAULT '모집중'
        )
    ''')
    
    # 2. applications 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER,
            name TEXT NOT NULL,
            dept TEXT NOT NULL,
            birthdate TEXT,
            phone TEXT NOT NULL,
            v1365_id TEXT,
            applied_at TEXT,
            attendance TEXT DEFAULT '대기',
            FOREIGN KEY (activity_id) REFERENCES activities (id)
        )
    ''')
    
    # 3. [스키마 마이그레이션] activities 컬럼 검사 및 자동 추가
    c.execute("PRAGMA table_info(activities)")
    act_cols = [row[1] for row in c.fetchall()]
    if 'deadline' not in act_cols:
        try:
            c.execute("ALTER TABLE activities ADD COLUMN deadline TEXT")
        except Exception:
            pass
    if 'status' not in act_cols:
        try:
            c.execute("ALTER TABLE activities ADD COLUMN status TEXT DEFAULT '모집중'")
        except Exception:
            pass

    # 4. [스키마 마이그레이션] applications 컬럼 검사 및 안전한 재배포 마이그레이션
    c.execute("PRAGMA table_info(applications)")
    app_col_info = c.fetchall()
    app_cols = [row[1] for row in app_col_info]
    
    has_emp_id = 'emp_id' in app_cols
    missing_birthdate = 'birthdate' not in app_cols
    missing_attendance = 'attendance' not in app_cols
    
    if has_emp_id:
        try:
            c.execute("ALTER TABLE applications RENAME TO applications_old")
            c.execute('''
                CREATE TABLE applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER,
                    name TEXT NOT NULL,
                    dept TEXT NOT NULL,
                    birthdate TEXT,
                    phone TEXT NOT NULL,
                    v1365_id TEXT,
                    applied_at TEXT,
                    attendance TEXT DEFAULT '대기',
                    FOREIGN KEY (activity_id) REFERENCES activities (id)
                )
            ''')
            
            c.execute("PRAGMA table_info(applications_old)")
            old_cols = [r[1] for r in c.fetchall()]
            
            birth_col = "birthdate" if "birthdate" in old_cols else "''"
            att_col = "attendance" if "attendance" in old_cols else "'대기'"
            v1365_col = "v1365_id" if "v1365_id" in old_cols else "''"
            
            c.execute(f'''
                INSERT INTO applications (id, activity_id, name, dept, birthdate, phone, v1365_id, applied_at, attendance)
                SELECT id, activity_id, name, dept, {birth_col}, phone, {v1365_col}, applied_at, {att_col}
                FROM applications_old
            ''')
            c.execute("DROP TABLE applications_old")
        except Exception:
            if missing_birthdate:
                try: c.execute("ALTER TABLE applications ADD COLUMN birthdate TEXT")
                except Exception: pass
            if missing_attendance:
                try: c.execute("ALTER TABLE applications ADD COLUMN attendance TEXT DEFAULT '대기'")
                except Exception: pass
    else:
        if missing_birthdate:
            try: c.execute("ALTER TABLE applications ADD COLUMN birthdate TEXT")
            except Exception: pass
        if missing_attendance:
            try: c.execute("ALTER TABLE applications ADD COLUMN attendance TEXT DEFAULT '대기'")
            except Exception: pass

    conn.commit()
    conn.close()

init_db()

# --- 헬퍼 함수 ---
def format_birthdate(birth_str):
    if not birth_str:
        return ""
    digits = re.sub(r'[^0-9]', '', str(birth_str))
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    elif len(digits) == 6:
        yy = int(digits[:2])
        prefix = "19" if yy > 25 else "20"
        return f"{prefix}{digits[:2]}-{digits[2:4]}-{digits[4:]}"
    return birth_str.strip()

def mask_phone(phone):
    p = str(phone).strip()
    if len(p) >= 10:
        return re.sub(r'(\d{3})[- ]?(\d{3,4})[- ]?(\d{4})', r'\1-****-\3', p)
    return p

def mask_birth(birth):
    b = str(birth).strip()
    if len(b) == 10:
        return f"{b[:4]}-**-**"
    return b

# --- 2. 사이드바 메뉴 ---
st.sidebar.title("🤝 봉사활동 포털")
menu = st.sidebar.radio("메뉴 선택", ["봉사활동 신청 (직원용)", "활동별 참여자 현황 및 본인 취소", "관리자 모드"])

# --- 3. [직원용] 봉사활동 신청 화면 ---
if menu == "봉사활동 신청 (직원용)":
    st.title("🌱 사내 봉사활동 신청")
    st.caption("참여를 희망하는 봉사활동을 선택하고 신청서를 작성해주세요.")

    conn = get_db()
    activities_df = pd.read_sql_query("SELECT * FROM activities ORDER BY date ASC", conn)
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    if activities_df.empty:
        st.info("현재 등록된 봉사활동 일감이 없습니다.")
    else:
        act_options = {}
        for _, act in activities_df.iterrows():
            act_id = act['id']
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (act_id,))
            current_count = c.fetchone()[0]
            max_cap = act['max_capacity']
            remain = max_cap - current_count
            
            deadline_str = act['deadline'] if act['deadline'] else "마감일 없음"
            is_expired = False
            if act['deadline'] and act['deadline'] < now_str:
                is_expired = True

            current_status = act['status']
            if current_status == "모집중" and (remain <= 0 or is_expired):
                current_status = "모집마감"

            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    status_badge = "🟢 모집중" if current_status == "모집중" else ("🔴 모집마감" if current_status == "모집마감" else "⚫ 활동종료")
                    st.subheader(f"{act['title']} `[{status_badge}]`")
                    st.write(f"📅 **활동일시:** {act['date']} | 📍 **장소:** {act['location']} | ⏱️ **인정시간:** {act['hours']}시간")
                    st.write(f"⏳ **모집 마감일시:** {deadline_str}")
                    if act['description']:
                        st.write(f"📝 **내용:** {act['description']}")
                with col2:
                    st.metric(label="신청 현황", value=f"{current_count} / {max_cap} 명")
                    if current_status != "모집중":
                        st.error(current_status)

            if current_status == "모집중":
                label = f"[{act['date']}] {act['title']} (잔여 {remain}명 / 마감: {deadline_str})"
                act_options[label] = act_id

        st.divider()
        st.subheader("📋 참가 신청서 작성")

        if not act_options:
            st.warning("현재 신청 가능한 봉사활동이 없습니다.")
        else:
            with st.form("apply_form", clear_on_submit=True):
                selected_act_label = st.selectbox("신청할 봉사활동 선택 *", list(act_options.keys()))
                
                name = st.text_input("1. 성명 *", placeholder="예: 홍길동")
                dept = st.text_input("2. 소속 부서 *", placeholder="예: 인사총무팀")
                birthdate = st.text_input("3. 생년월일 (YYYY-MM-DD) *", placeholder="예: 1980-06-02")
                phone = st.text_input("4. 휴대폰 번호 *", placeholder="예: 010-1234-5678")
                v1365_id = st.text_input("5. 1365 자원봉사포털 ID (선택 - 실적 연계용)", placeholder="1365 아이디 입력")
                
                submit = st.form_submit_button("봉사활동 신청하기", use_container_width=True)

                if submit:
                    selected_id = act_options[selected_act_label]
                    if not (name.strip() and dept.strip() and birthdate.strip() and phone.strip()):
                        st.warning("필수 정보(성명, 소속 부서, 생년월일, 휴대폰 번호)를 모두 입력해주세요.")
                    else:
                        formatted_birth = format_birthdate(birthdate)
                        clean_phone = phone.strip()
                        
                        c = conn.cursor()
                        c.execute('''
                            SELECT id FROM applications 
                            WHERE activity_id = ? AND name = ? AND birthdate = ?
                        ''', (selected_id, name.strip(), formatted_birth))
                        if c.fetchone():
                            st.error("이미 신청하신 봉사활동입니다.")
                        else:
                            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (selected_id,))
                            count_now = c.fetchone()[0]
                            c.execute("SELECT max_capacity FROM activities WHERE id = ?", (selected_id,))
                            cap = c.fetchone()[0]

                            if count_now >= cap:
                                st.error("신청하는 도중 정원이 마감되었습니다.")
                            else:
                                now_apply = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute('''
                                    INSERT INTO applications (activity_id, name, dept, birthdate, phone, v1365_id, applied_at, attendance)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, '대기')
                                ''', (selected_id, name.strip(), dept.strip(), formatted_birth, clean_phone, v1365_id.strip(), now_apply))
                                conn.commit()
                                st.success(f"{name}님, 선착순 신청이 정상 완료되었습니다! (생년월일: {formatted_birth})")
                                st.balloons()
                                st.rerun()
    conn.close()

# --- 4. [직원용] 봉사활동별 참여자 현황 & 본인 직접 취소 ---
elif menu == "활동별 참여자 현황 및 본인 취소":
    st.title("👥 봉사활동별 참여자 명단 및 신청 취소")
    conn = get_db()
    
    acts = pd.read_sql_query("SELECT id, title, date, location, hours, max_capacity, status FROM activities ORDER BY date DESC", conn)
    
    if acts.empty:
        st.info("등록된 봉사활동이 없습니다.")
    else:
        act_map = {f"[{row['status']}] [{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
        selected_act_label = st.selectbox("조회할 봉사활동을 선택하세요", list(act_map.keys()))
        target_act_id = act_map[selected_act_label]

        act_info = acts[acts['id'] == target_act_id].iloc[0]
        st.write(f"📍 **장소:** {act_info['location']} | ⏱️ **인정시간:** {act_info['hours']}시간 | 🎯 **정원:** {act_info['max_capacity']}명 | 📌 **상태:** `{act_info['status']}`")

        query = '''
            SELECT id, name, dept, birthdate, phone, applied_at, attendance
            FROM applications
            WHERE activity_id = ?
            ORDER BY id ASC
        '''
        apps_df = pd.read_sql_query(query, conn, params=(target_act_id,))

        st.subheader("📋 실시간 신청자 명단 (선착순)")
        if apps_df.empty:
            st.info("아직 신청자가 없습니다.")
        else:
            apps_df.insert(0, '순번', range(1, len(apps_df) + 1))
            display_df = apps_df.copy()
            display_df['생년월일'] = display_df['birthdate'].apply(mask_birth)
            display_df['휴대폰번호'] = display_df['phone'].apply(mask_phone)
            
            if act_info['status'] == "활동종료":
                view_cols = ['순번', 'name', 'dept', '생년월일', '휴대폰번호', 'applied_at', 'attendance']
                col_names = ['선착순 번호', '성명', '소속부서', '생년월일', '연락처', '신청일시', '최종 참석여부']
            else:
                view_cols = ['순번', 'name', 'dept', '생년월일', '휴대폰번호', 'applied_at']
                col_names = ['선착순 번호', '성명', '소속부서', '생년월일', '연락처', '신청일시']
                
            display_df = display_df[view_cols]
            display_df.columns = col_names
            st.dataframe(display_df, use_container_width=True)

        st.divider()
        st.subheader("❌ 내 신청 직접 취소하기")
        st.caption("신청 시 작성했던 정보를 입력하면 본인 확인 후 즉시 취소됩니다.")
        
        with st.form("cancel_form", clear_on_submit=True):
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                c_name = st.text_input("성명", placeholder="홍길동")
            with col_c2:
                c_birth = st.text_input("생년월일", placeholder="1980-06-02")
            with col_c3:
                c_phone = st.text_input("휴대폰 번호", placeholder="010-1234-5678")
            
            cancel_btn = st.form_submit_button("신청 취소하기", type="primary", use_container_width=True)
            
            if cancel_btn:
                if not (c_name.strip() and c_birth.strip() and c_phone.strip()):
                    st.warning("본인 확인을 위해 성명, 생년월일, 휴대폰 번호를 모두 입력해주세요.")
                else:
                    fmt_cbirth = format_birthdate(c_birth)
                    c = conn.cursor()
                    c.execute('''
                        SELECT id FROM applications 
                        WHERE activity_id = ? AND name = ? AND birthdate = ? AND phone = ?
                    ''', (target_act_id, c_name.strip(), fmt_cbirth, c_phone.strip()))
                    matched = c.fetchone()
                    
                    if matched:
                        c.execute("DELETE FROM applications WHERE id = ?", (matched[0],))
                        conn.commit()
                        st.success(f"{c_name}님의 봉사활동 신청이 정상적으로 취소되었습니다.")
                        st.rerun()
                    else:
                        st.error("일치하는 신청 내역을 찾을 수 없습니다. 입력하신 정보를 다시 확인해주세요.")
    conn.close()

# --- 5. [관리자용] 관리자 대시보드 ---
elif menu == "관리자 모드":
    st.title("🛠️ 관리자 대시보드")
    admin_password = st.sidebar.text_input("관리자 비밀번호", type="password")
    
    if admin_password != "admin1234":
        st.warning("사이드바에 올바른 관리자 비밀번호를 입력해주세요. (기본: admin1234)")
    else:
        tab1, tab2, tab3 = st.tabs(["일감 등록 및 모집/마감 관리", "출석 체크 & 현장 참석자 추가 & 엑셀", "신청자 수기 대리등록"])
        conn = get_db()

        # [탭 1] 일감 등록 및 모집/마감/일정 변경
        with tab1:
            st.subheader("➕ 신규 봉사 일감 등록")
            with st.form("add_activity_form", clear_on_submit=True):
                title = st.text_input("봉사활동명 *", placeholder="예: 봄맞이 한강 정화 플로깅")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    date = st.text_input("봉사 활동 일시 *", placeholder="예: 2026-09-12 14:00~17:00")
                with col_d2:
                    deadline = st.text_input("모집 마감 일시 (선택)", placeholder="예: 2026-09-10 18:00")
                
                col_h, col_c = st.columns(2)
                with col_h:
                    hours = st.number_input("인정 시간 (시간 단위)", min_value=0.5, step=0.5, value=2.0)
                with col_c:
                    capacity = st.number_input("모집 정원 (명)", min_value=1, step=1, value=10)
                
                location = st.text_input("집결/활동 장소 *", placeholder="예: 김포한강중앙공원 야외무대")
                description = st.text_area("상세 안내 및 준비물", placeholder="편한 복장, 개인 텀블러 지참 등")
                
                if st.form_submit_button("새 일감 등록하기", use_container_width=True):
                    if title.strip() and date.strip() and location.strip():
                        c = conn.cursor()
                        c.execute('''
                            INSERT INTO activities (title, date, deadline, location, hours, max_capacity, description, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, '모집중')
                        ''', (title.strip(), date.strip(), deadline.strip(), location.strip(), hours, capacity, description.strip()))
                        conn.commit()
                        st.success("새로운 일감이 등록되었습니다.")
                        st.rerun()
                    else:
                        st.error("필수 항목(활동명, 활동일시, 장소)을 입력해주세요.")

            st.divider()
            st.subheader("📋 일감 상태 관리 (모집중 / 마감 / 종료 / 삭제)")
            all_acts = pd.read_sql_query("SELECT * FROM activities ORDER BY id DESC", conn)
            
            if all_acts.empty:
                st.info("등록된 일감이 없습니다.")
            else:
                for _, act in all_acts.iterrows():
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([3, 1.2, 1.2, 1])
                        with c1:
                            st.write(f"**[{act['status']}] {act['title']}** (ID: {act['id']})")
                            st.write(f"📅 활동일시: {act['date']} | ⏳ 마감일시: {act['deadline'] or '미지정'} | 📍 {act['location']}")
                            st.write(f"정원: {act['max_capacity']}명 | 인정시간: {act['hours']}시간")
                        
                        with c2:
                            status_choices = ["모집중", "모집마감", "활동종료"]
                            curr_idx = status_choices.index(act['status']) if act['status'] in status_choices else 0
                            new_st = st.selectbox("상태 변경", status_choices, index=curr_idx, key=f"sel_st_{act['id']}")
                            if st.button("상태 저장", key=f"btn_st_{act['id']}"):
                                c = conn.cursor()
                                c.execute("UPDATE activities SET status = ? WHERE id = ?", (new_st, act['id']))
                                conn.commit()
                                st.success("상태가 변경되었습니다.")
                                st.rerun()
                        
                        with c3:
                            new_dl = st.text_input("마감일시 수정", value=act['deadline'] or "", key=f"edit_dl_{act['id']}")
                            if st.button("마감일 저장", key=f"btn_dl_{act['id']}"):
                                c = conn.cursor()
                                c.execute("UPDATE activities SET deadline = ? WHERE id = ?", (new_dl.strip(), act['id']))
                                conn.commit()
                                st.success("마감일시가 수정되었습니다.")
                                st.rerun()

                        with c4:
                            st.write("")
                            st.write("")
                            if st.button("일감 삭제", key=f"del_act_{act['id']}", type="primary"):
                                c = conn.cursor()
                                c.execute("DELETE FROM applications WHERE activity_id = ?", (act['id'],))
                                c.execute("DELETE FROM activities WHERE id = ?", (act['id'],))
                                conn.commit()
                                st.warning("일감이 삭제되었습니다.")
                                st.rerun()

        # [탭 2] 현장 출석 체크, 현장 신규/대체자 추가, 엑셀 다운로드
        with tab2:
            st.subheader("👥 출석 관리 & 현장 대체자 등록 & 실적 엑셀")
            acts = pd.read_sql_query("SELECT id, title, date, status FROM activities ORDER BY id DESC", conn)
            
            if acts.empty:
                st.info("등록된 일감이 없습니다.")
            else:
                act_select_map = {f"[{row['status']}] [{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                target_act_name = st.selectbox("관리할 활동 선택", list(act_select_map.keys()), key="admin_att_act")
                target_act_id = act_select_map[target_act_name]

                app_df = pd.read_sql_query('''
                    SELECT id, name, dept, birthdate, phone, v1365_id, applied_at, attendance
                    FROM applications
                    WHERE activity_id = ?
                    ORDER BY id ASC
                ''', conn, params=(target_act_id,))

                col_ex1, col_ex2 = st.columns(2)
                with col_ex1:
                    if not app_df.empty:
                        out_all = io.BytesIO()
                        with pd.ExcelWriter(out_all, engine='xlsxwriter') as writer:
                            app_df.to_excel(writer, index=False, sheet_name='전체출석부')
                        st.download_button(
                            label="📥 전체 신청자 출석부 엑셀 다운로드",
                            data=out_all.getvalue(),
                            file_name=f"봉사활동_출석부_{target_act_id}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                with col_ex2:
                    if not app_df.empty:
                        attended_df = app_df[app_df['attendance'] == '참석']
                        out_att = io.BytesIO()
                        with pd.ExcelWriter(out_att, engine='xlsxwriter') as writer:
                            attended_df[['name', 'birthdate', 'dept', 'phone', 'v1365_id', 'applied_at']].to_excel(
                                writer, index=False, sheet_name='1365인정대상'
                            )
                        st.download_button(
                            label="⭐ [1365 제출용] 최종 참석자 엑셀 다운로드",
                            data=out_att.getvalue(),
                            file_name=f"1365_최종참석자명단_{target_act_id}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )

                st.divider()
                st.subheader("✅ 실시간 출석 체크 (참석 / 불참 / 대기)")
                if app_df.empty:
                    st.info("신청자가 없습니다.")
                else:
                    st.caption("각 직원의 출석 상태를 선택한 후 아래 [출석 상태 일괄 저장] 버튼을 눌러주세요.")
                    updated_attendance = {}
                    
                    for idx, row in app_df.iterrows():
                        with st.container(border=True):
                            c_info, c_att, c_del = st.columns([3, 2, 1])
                            with c_info:
                                st.write(f"**{idx+1}. {row['name']}** ({row['dept']} / {row['birthdate']})")
                                st.write(f"📞 {row['phone']} | 1365 ID: `{row['v1365_id'] or '미입력'}` | 신청: {row['applied_at']}")
                            with c_att:
                                current_att = row['attendance'] if row['attendance'] in ['대기', '참석', '불참'] else '대기'
                                choice = st.radio(
                                    "출석 상태",
                                    ["대기", "참석", "불참"],
                                    index=["대기", "참석", "불참"].index(current_att),
                                    key=f"att_radio_{row['id']}",
                                    horizontal=True
                                )
                                updated_attendance[row['id']] = choice
                            with c_del:
                                st.write("")
                                if st.button("신청 취소/삭제", key=f"del_user_{row['id']}"):
                                    c = conn.cursor()
                                    c.execute("DELETE FROM applications WHERE id = ?", (row['id'],))
                                    conn.commit()
                                    st.warning(f"{row['name']}님이 삭제되었습니다.")
                                    st.rerun()

                    if st.button("💾 출석 체크 결과 일괄 저장", type="primary", use_container_width=True):
                        c = conn.cursor()
                        for app_id, att_val in updated_attendance.items():
                            c.execute("UPDATE applications SET attendance = ? WHERE id = ?", (att_val, app_id))
                        conn.commit()
                        st.success("출석 상태가 성공적으로 저장되었습니다!")
                        st.rerun()

                st.divider()
                st.subheader("➕ 당일 현장 신규/대체 참석자 추가")
                st.caption("사전 신청 없이 당일 현장에 새로 오거나 다른 사람 대신 온 직원을 즉시 추가합니다.")
                
                with st.form("add_onsite_form", clear_on_submit=True):
                    col_on1, col_on2 = st.columns(2)
                    with col_on1:
                        on_name = st.text_input("성명 *", placeholder="홍길동")
                        on_dept = st.text_input("소속 부서 *", placeholder="인사총무팀")
                    with col_on2:
                        on_birth = st.text_input("생년월일 (YYYY-MM-DD) *", placeholder="1980-06-02")
                        on_phone = st.text_input("휴대폰 번호 *", placeholder="010-0000-0000")
                    on_1365 = st.text_input("1365 ID (선택)", placeholder="1365 아이디")
                    
                    if st.form_submit_button("현장 참석자로 즉시 추가 (출석 완료 처리)", use_container_width=True):
                        if on_name.strip() and on_dept.strip() and on_birth.strip() and on_phone.strip():
                            formatted_on_birth = format_birthdate(on_birth)
                            now_str_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S (현장추가)")
                            c = conn.cursor()
                            c.execute('''
                                INSERT INTO applications (activity_id, name, dept, birthdate, phone, v1365_id, applied_at, attendance)
                                VALUES (?, ?, ?, ?, ?, ?, ?, '참석')
                            ''', (target_act_id, on_name.strip(), on_dept.strip(), formatted_on_birth, on_phone.strip(), on_1365.strip(), now_str_on))
                            conn.commit()
                            st.success(f"{on_name} 직원이 현장 참석자(참석 완료)로 명단에 추가되었습니다.")
                            st.rerun()
                        else:
                            st.warning("필수 정보(성명, 부서, 생년월일, 연락처)를 모두 입력해주세요.")

        # [탭 3] 관리자 수기 대리 등록
        with tab3:
            st.subheader("✍️ 사전 신청자 수기 대리등록")
            st.caption("전화나 메신저로 접수된 인원을 관리자가 대리로 사전 등록합니다.")
            
            acts = pd.read_sql_query("SELECT id, title, date FROM activities ORDER BY id DESC", conn)
            if acts.empty:
                st.info("등록된 일감이 없습니다.")
            else:
                act_map = {f"[{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                with st.form("admin_manual_apply_form", clear_on_submit=True):
                    sel_act = st.selectbox("봉사활동 선택", list(act_map.keys()))
                    m_name = st.text_input("1. 성명 *", placeholder="예: 김철수")
                    m_dept = st.text_input("2. 소속 부서 *", placeholder="예: 인사총무팀")
                    m_birth = st.text_input("3. 생년월일 (YYYY-MM-DD) *", placeholder="예: 1980-06-02")
                    m_phone = st.text_input("4. 휴대폰 번호 *", placeholder="010-0000-0000")
                    m_1365 = st.text_input("5. 1365 ID (선택)", placeholder="1365 아이디")
                    
                    if st.form_submit_button("신청자 대리등록 완료", use_container_width=True):
                        if m_name.strip() and m_dept.strip() and m_birth.strip() and m_phone.strip():
                            target_id = act_map[sel_act]
                            formatted_m_birth = format_birthdate(m_birth)
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S (관리자등록)")
                            c = conn.cursor()
                            c.execute('''
                                INSERT INTO applications (activity_id, name, dept, birthdate, phone, v1365_id, applied_at, attendance)
                                VALUES (?, ?, ?, ?, ?, ?, ?, '대기')
                            ''', (target_id, m_name.strip(), m_dept.strip(), formatted_m_birth, m_phone.strip(), m_1365.strip(), now_str))
                            conn.commit()
                            st.success(f"{m_name} 직원이 사전 신청자로 등록되었습니다.")
                            st.rerun()
                        else:
                            st.warning("필수 정보(성명, 부서, 생년월일, 연락처)를 모두 입력해주세요.")

        conn.close()
