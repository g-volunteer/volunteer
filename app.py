import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io

# --- 1. 기본 설정 및 DB 초기화 ---
st.set_page_config(
    page_title="임직원 봉사활동 신청 시스템",
    page_icon="🤝",
    layout="wide"
)

DB_NAME = "volunteer_system.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # 봉사 일감 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            location TEXT NOT NULL,
            hours REAL NOT NULL,
            max_capacity INTEGER NOT NULL,
            description TEXT,
            status TEXT DEFAULT '모집중'
        )
    ''')
    # 신청자 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER,
            emp_id TEXT NOT NULL,
            name TEXT NOT NULL,
            dept TEXT NOT NULL,
            phone TEXT NOT NULL,
            v1365_id TEXT,
            applied_at TEXT,
            FOREIGN KEY (activity_id) REFERENCES activities (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- 2. 사이드바 메뉴 구성 ---
st.sidebar.title("🤝 봉사활동 포털")
menu = st.sidebar.radio("메뉴 선택", ["봉사활동 신청 (직원용)", "신청 내역 확인/취소 (이름 검색)", "관리자 모드"])

# --- 3. [직원용] 봉사활동 신청 화면 ---
if menu == "봉사활동 신청 (직원용)":
    st.title("🌱 사내 봉사활동 신청")
    st.caption("참여를 희망하는 봉사활동을 선택하고 신청서를 작성해주세요.")

    conn = get_db()
    activities_df = pd.read_sql_query("SELECT * FROM activities WHERE status = '모집중' ORDER BY date ASC", conn)
    
    if activities_df.empty:
        st.info("현재 모집 중인 봉사활동 일감이 없습니다.")
    else:
        act_options = {}
        for _, act in activities_df.iterrows():
            act_id = act['id']
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (act_id,))
            current_count = c.fetchone()[0]
            max_cap = act['max_capacity']
            remain = max_cap - current_count
            is_full = current_count >= max_cap

            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.subheader(f"{act['title']} {'[마감]' if is_full else ''}")
                    st.write(f"📅 **일시:** {act['date']} | 📍 **장소:** {act['location']} | ⏱️ **인정시간:** {act['hours']}시간")
                    st.write(f"📝 **내용:** {act['description']}")
                with col2:
                    st.metric(label="모집 현황", value=f"{current_count} / {max_cap} 명")
                    if is_full:
                        st.error("정원 마감")

            label = f"[{act['date']}] {act['title']} (잔여 {max(0, remain)}명)"
            act_options[label] = act_id

        st.divider()
        st.subheader("📋 참가 신청서 작성")

        with st.form("apply_form", clear_on_submit=True):
            selected_act_label = st.selectbox("신청할 봉사활동 선택", list(act_options.keys()))
            
            c1, c2 = st.columns(2)
            with c1:
                dept = st.text_input("소속 부서", placeholder="예: 기획홍보팀")
                emp_id = st.text_input("사번", placeholder="예: 20240101")
            with c2:
                name = st.text_input("성명", placeholder="예: 홍길동")
                phone = st.text_input("연락처 (휴대폰)", placeholder="010-0000-0000")
            
            v1365_id = st.text_input("1365 자원봉사포털 ID (선택 - 실적 연계용)", placeholder="1365 아이디 입력")
            
            submit = st.form_submit_button("봉사활동 신청하기", use_container_width=True)

            if submit:
                selected_id = act_options[selected_act_label]
                if not (dept and emp_id and name and phone):
                    st.warning("필수 정보(부서, 사번, 성명, 연락처)를 모두 입력해주세요.")
                else:
                    c = conn.cursor()
                    c.execute("SELECT id FROM applications WHERE activity_id = ? AND emp_id = ?", (selected_id, emp_id))
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
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            c.execute('''
                                INSERT INTO applications (activity_id, emp_id, name, dept, phone, v1365_id, applied_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''', (selected_id, emp_id, name, dept, phone, v1365_id, now_str))
                            conn.commit()
                            st.success(f"{name}님, 신청이 정상적으로 완료되었습니다!")
                            st.balloons()
    conn.close()

# --- 4. [직원용] 신청 내역 확인/취소 (이름 검색 + 동명이인 부서 구분) ---
elif menu == "신청 내역 확인/취소 (이름 검색)":
    st.title("🔍 내 신청 내역 조회")
    st.caption("이름을 입력하여 본인의 신청 내역을 확인하거나 취소할 수 있습니다.")
    conn = get_db()
    
    search_name = st.text_input("성명을 입력하세요", placeholder="예: 홍길동").strip()
    
    if search_name:
        # 해당 이름을 가진 사용자 고유 목록 조회 (동명이인 확인용)
        user_query = '''
            SELECT DISTINCT name, dept, emp_id, phone 
            FROM applications 
            WHERE name = ?
        '''
        users_df = pd.read_sql_query(user_query, conn, params=(search_name,))
        
        if users_df.empty:
            st.info(f"'{search_name}' 이름으로 신청된 내역이 없습니다.")
        else:
            selected_emp_id = None
            
            # 동명이인이 2명 이상 있는 경우 부서/사번으로 선택하게 함
            if len(users_df) > 1:
                st.warning(f"동명이인이 {len(users_df)}명 존재합니다. 본인의 부서 정보를 선택해주세요.")
                options = {
                    f"{row['name']} ({row['dept']} / 사번: {row['emp_id']} / 연락처 뒷자리: {row['phone'][-4:] if len(row['phone'])>=4 else row['phone']})": row['emp_id']
                    for _, row in users_df.iterrows()
                }
                selected_user_label = st.selectbox("본인 정보 선택", list(options.keys()))
                selected_emp_id = options[selected_user_label]
            else:
                selected_emp_id = users_df.iloc[0]['emp_id']
                st.write(f"👉 **확인된 정보:** {users_df.iloc[0]['name']} ({users_df.iloc[0]['dept']} / 사번: {users_df.iloc[0]['emp_id']})")

            # 선택된 사번의 신청 내역 조회
            if selected_emp_id:
                query = '''
                    SELECT a.id as app_id, act.title, act.date, act.location, act.hours, a.name, a.dept, a.applied_at
                    FROM applications a
                    JOIN activities act ON a.activity_id = act.id
                    WHERE a.emp_id = ?
                    ORDER BY act.date DESC
                '''
                my_apps = pd.read_sql_query(query, conn, params=(selected_emp_id,))
                
                if my_apps.empty:
                    st.info("신청 내역이 없습니다.")
                else:
                    st.write(f"총 **{len(my_apps)}건**의 신청 내역이 있습니다.")
                    for _, row in my_apps.iterrows():
                        with st.container(border=True):
                            st.write(f"📌 **{row['title']}**")
                            st.write(f"📅 **일시:** {row['date']} | 📍 **장소:** {row['location']} | ⏱️ **인정시간:** {row['hours']}시간")
                            st.write(f"🕒 **신청일시:** {row['applied_at']}")
                            
                            if st.button("신청 취소", key=f"user_cancel_{row['app_id']}"):
                                c = conn.cursor()
                                c.execute("DELETE FROM applications WHERE id = ?", (row['app_id'],))
                                conn.commit()
                                st.warning("신청이 정상적으로 취소되었습니다.")
                                st.rerun()
    conn.close()

# --- 5. [관리자용] 관리자 대시보드 ---
elif menu == "관리자 모드":
    st.title("🛠️ 관리자 대시보드")
    admin_password = st.sidebar.text_input("관리자 비밀번호", type="password")
    
    if admin_password != "admin1234":
        st.warning("사이드바에 올바른 관리자 비밀번호를 입력해주세요.")
    else:
        tab1, tab2, tab3 = st.tabs(["일감 등록 및 관리", "신청자 관리 (조회/삭제/엑셀)", "신청자 수기 대리등록"])
        conn = get_db()

        # [탭 1] 신규 일감 등록 및 삭제/상태변경
        with tab1:
            st.subheader("➕ 신규 봉사 일감 등록")
            with st.form("add_activity_form", clear_on_submit=True):
                title = st.text_input("봉사활동명", placeholder="예: 봄맞이 한강 정화 플로깅")
                col_d, col_h, col_c = st.columns(3)
                with col_d:
                    date = st.text_input("활동 일시", placeholder="예: 2026-05-15 14:00~17:00")
                with col_h:
                    hours = st.number_input("인정 시간 (시간 단위)", min_value=0.5, step=0.5, value=2.0)
                with col_c:
                    capacity = st.number_input("모집 정원 (명)", min_value=1, step=1, value=10)
                location = st.text_input("집결/활동 장소", placeholder="예: 김포한강중앙공원 야외무대")
                description = st.text_area("활동 상세 안내 및 준비물", placeholder="편한 복장, 개인 텀블러 지참 등")
                
                if st.form_submit_button("일감 등록하기", use_container_width=True):
                    if title and date and location:
                        c = conn.cursor()
                        c.execute('''
                            INSERT INTO activities (title, date, location, hours, max_capacity, description)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (title, date, location, hours, capacity, description))
                        conn.commit()
                        st.success("새로운 일감이 성공적으로 등록되었습니다.")
                        st.rerun()
                    else:
                        st.error("필수 항목(활동명, 일시, 장소)을 입력해주세요.")

            st.divider()
            st.subheader("📋 등록된 일감 목록 및 관리")
            all_acts = pd.read_sql_query("SELECT id, title, date, location, hours, max_capacity, status FROM activities ORDER BY id DESC", conn)
            
            if all_acts.empty:
                st.info("등록된 일감이 없습니다.")
            else:
                for _, act in all_acts.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([3, 1, 1])
                        with c1:
                            st.write(f"**[{act['status']}] {act['title']}** (ID: {act['id']})")
                            st.write(f"일시: {act['date']} | 장소: {act['location']} | 정원: {act['max_capacity']}명 | 시간: {act['hours']}h")
                        with c2:
                            new_status = "마감" if act['status'] == "모집중" else "모집중"
                            if st.button(f"상태를 '{new_status}'으로 변경", key=f"status_{act['id']}"):
                                c = conn.cursor()
                                c.execute("UPDATE activities SET status = ? WHERE id = ?", (new_status, act['id']))
                                conn.commit()
                                st.rerun()
                        with c3:
                            if st.button("일감 삭제", key=f"del_act_{act['id']}", type="primary"):
                                c = conn.cursor()
                                c.execute("DELETE FROM applications WHERE activity_id = ?", (act['id'],))
                                c.execute("DELETE FROM activities WHERE id = ?", (act['id'],))
                                conn.commit()
                                st.warning("일감 및 해당 신청 내역이 삭제되었습니다.")
                                st.rerun()

        # [탭 2] 신청자 명단 조회, 개별 삭제, 엑셀 다운로드
        with tab2:
            st.subheader("👥 신청자 명단 관리 및 엑셀 추출")
            acts = pd.read_sql_query("SELECT id, title, date FROM activities ORDER BY id DESC", conn)
            
            if acts.empty:
                st.info("등록된 일감이 없습니다.")
            else:
                act_select_map = {f"[{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                target_act_name = st.selectbox("조회할 활동 선택", list(act_select_map.keys()), key="admin_view_act")
                target_act_id = act_select_map[target_act_name]

                # 신청자 쿼리
                query = '''
                    SELECT id AS '신청ID', emp_id AS '사번', name AS '성명', dept AS '부서', phone AS '연락처', 
                           v1365_id AS '1365 ID', applied_at AS '신청일시'
                    FROM applications
                    WHERE activity_id = ?
                    ORDER BY applied_at ASC
                '''
                app_df = pd.read_sql_query(query, conn, params=(target_act_id,))
                
                st.write(f"**총 신청 인원:** {len(app_df)}명")
                st.dataframe(app_df, use_container_width=True)

                if not app_df.empty:
                    # 엑셀 다운로드
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        # 엑셀 저장 시 신청ID 제외 깔끔하게 저장
                        excel_df = app_df.drop(columns=['신청ID'])
                        excel_df.to_excel(writer, index=False, sheet_name='신청자명단')
                    excel_data = output.getvalue()

                    st.download_button(
                        label="📥 1365 실적 등록/출석용 엑셀 다운로드",
                        data=excel_data,
                        file_name=f"봉사활동_신청자명단_{target_act_id}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                    st.divider()
                    st.subheader("🗑️ 특정 신청자 취소/삭제")
                    del_options = {
                        f"ID:{row['신청ID']} | {row['성명']} ({row['부서']} - 사번:{row['사번']})": row['신청ID']
                        for _, row in app_df.iterrows()
                    }
                    selected_del_label = st.selectbox("삭제할 신청자를 선택하세요", list(del_options.keys()))
                    
                    if st.button("선택한 신청자 삭제하기", type="primary"):
                        target_del_id = del_options[selected_del_label]
                        c = conn.cursor()
                        c.execute("DELETE FROM applications WHERE id = ?", (target_del_id,))
                        conn.commit()
                        st.success("해당 신청자가 성공적으로 취소/삭제되었습니다.")
                        st.rerun()

        # [탭 3] 관리자가 대신 수기 신청 등록
        with tab3:
            st.subheader("✍️ 신청자 수기 등록 (관리자 대리 신청)")
            st.caption("현장 접수나 전화로 신청한 직원을 관리자가 직접 등록합니다.")
            
            acts = pd.read_sql_query("SELECT id, title, date FROM activities WHERE status = '모집중' ORDER BY id DESC", conn)
            if acts.empty:
                st.info("현재 모집 중인 활동이 없습니다.")
            else:
                act_map = {f"[{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                with st.form("admin_manual_apply_form", clear_on_submit=True):
                    sel_act = st.selectbox("봉사활동 선택", list(act_map.keys()))
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        m_dept = st.text_input("소속 부서", placeholder="예: 행정복지팀")
                        m_emp_id = st.text_input("사번", placeholder="예: 20230101")
                    with col_m2:
                        m_name = st.text_input("성명", placeholder="예: 김철수")
                        m_phone = st.text_input("연락처", placeholder="010-0000-0000")
                    m_1365 = st.text_input("1365 ID (선택)", placeholder="1365 아이디")
                    
                    if st.form_submit_button("신청자 등록 완료", use_container_width=True):
                        if m_dept and m_emp_id and m_name and m_phone:
                            target_id = act_map[sel_act]
                            c = conn.cursor()
                            # 중복 검사
                            c.execute("SELECT id FROM applications WHERE activity_id = ? AND emp_id = ?", (target_id, m_emp_id))
                            if c.fetchone():
                                st.error("해당 사번으로 이미 신청되어 있습니다.")
                            else:
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute('''
                                    INSERT INTO applications (activity_id, emp_id, name, dept, phone, v1365_id, applied_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                ''', (target_id, m_emp_id, m_name, m_dept, m_phone, m_1365, now_str))
                                conn.commit()
                                st.success(f"{m_name} 직원이 성공적으로 등록되었습니다.")
                                st.rerun()
                        else:
                            st.warning("필수 정보(부서, 사번, 성명, 연락처)를 모두 입력해주세요.")

        conn.close()
