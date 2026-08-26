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
menu = st.sidebar.radio("메뉴 선택", ["봉사활동 신청 (직원용)", "신청 내역 확인/취소", "관리자 모드"])

# --- 3. [직원용] 봉사활동 신청 화면 ---
if menu == "봉사활동 신청 (직원용)":
    st.title("🌱 사내 봉사활동 신청")
    st.caption("참여를 희망하는 봉사활동을 선택하고 신청서를 작성해주세요.")

    conn = get_db()
    activities_df = pd.read_sql_query("SELECT * FROM activities WHERE status = '모집중' ORDER BY date ASC", conn)
    
    if activities_df.empty:
        st.info("현재 모집 중인 봉사활동 일감이 없습니다.")
    else:
        # 활동 카드 형태로 표시
        for _, act in activities_df.iterrows():
            act_id = act['id']
            # 신청자 수 집계
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (act_id,))
            current_count = c.fetchone()[0]
            max_cap = act['max_capacity']
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

        st.divider()
        st.subheader("📋 참가 신청서 작성")

        # 신청 폼
        act_options = {f"[{act['date']}] {act['title']} (잔여 {act['max_capacity'] - pd.read_sql_query(f'SELECT COUNT(*) as c FROM applications WHERE activity_id = {act[\"id\"]}', conn).iloc[0]['c']}명)": act['id'] 
                       for _, act in activities_df.iterrows()}
        
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
                    # 중복 신청 체크
                    c = conn.cursor()
                    c.execute("SELECT id FROM applications WHERE activity_id = ? AND emp_id = ?", (selected_id, emp_id))
                    if c.fetchone():
                        st.error("이미 신청하신 봉사활동입니다.")
                    else:
                        # 정원 재확인
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

# --- 4. [직원용] 신청 내역 확인/취소 ---
elif menu == "신청 내역 확인/취소":
    st.title("🔍 내 신청 내역 조회")
    conn = get_db()
    
    search_emp_id = st.text_input("사번을 입력하세요", placeholder="사번 입력 후 엔터")
    if search_emp_id:
        query = '''
            SELECT a.id as app_id, act.title, act.date, act.location, act.hours, a.name, a.dept, a.applied_at
            FROM applications a
            JOIN activities act ON a.activity_id = act.id
            WHERE a.emp_id = ?
            ORDER BY act.date DESC
        '''
        my_apps = pd.read_sql_query(query, conn, params=(search_emp_id,))
        if my_apps.empty:
            st.info("신청 내역이 없습니다.")
        else:
            for _, row in my_apps.iterrows():
                with st.container(border=True):
                    st.write(f"📌 **{row['title']}** ({row['date']})")
                    st.write(f"장소: {row['location']} | 시간: {row['hours']}시간 | 신청일시: {row['applied_at']}")
                    
                    if st.button("신청 취소", key=f"cancel_{row['app_id']}"):
                        c = conn.cursor()
                        c.execute("DELETE FROM applications WHERE id = ?", (row['app_id'],))
                        conn.commit()
                        st.warning("신청이 취소되었습니다.")
                        st.rerun()
    conn.close()

# --- 5. [관리자용] 관리자 모드 ---
elif menu == "관리자 모드":
    st.title("🛠️ 관리자 대시보드")
    admin_password = st.sidebar.text_input("관리자 비밀번호", type="password")
    
    # 기본 임시 비밀번호 설정 (운영 시 변경 필요)
    if admin_password != "admin1234":
        st.warning("사이드바에 올바른 관리자 비밀번호를 입력해주세요.")
    else:
        tab1, tab2 = st.tabs(["일감 등록 및 관리", "신청자 명단 및 1365 엑셀 다운로드"])
        conn = get_db()

        # 탭 1: 신규 일감 등록
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
            st.subheader("📋 등록된 일감 목록")
            all_acts = pd.read_sql_query("SELECT id, title, date, location, hours, max_capacity, status FROM activities ORDER BY id DESC", conn)
            st.dataframe(all_acts, use_container_width=True)

        # 탭 2: 신청자 명단 조회 및 엑셀 다운로드
        with tab2:
            st.subheader("👥 신청자 명단 조회 및 추출")
            acts = pd.read_sql_query("SELECT id, title, date FROM activities ORDER BY id DESC", conn)
            
            if acts.empty:
                st.info("등록된 일감이 없습니다.")
            else:
                act_select_map = {f"[{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                target_act_name = st.selectbox("조회할 활동 선택", list(act_select_map.keys()))
                target_act_id = act_select_map[target_act_name]

                # 신청자 쿼리
                query = '''
                    SELECT emp_id AS '사번', name AS '성명', dept AS '부서', phone AS '연락처', 
                           v1365_id AS '1365 ID', applied_at AS '신청일시'
                    FROM applications
                    WHERE activity_id = ?
                    ORDER BY applied_at ASC
                '''
                app_df = pd.read_sql_query(query, conn, params=(target_act_id,))
                
                st.write(f"**총 신청자:** {len(app_df)}명")
                st.dataframe(app_df, use_container_width=True)

                if not app_df.empty:
                    # 엑셀 파일 생성
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        app_df.to_excel(writer, index=False, sheet_name='신청자명단')
                    excel_data = output.getvalue()

                    st.download_button(
                        label="📥 1365 실적 등록/출석용 엑셀 다운로드",
                        data=excel_data,
                        file_name=f"봉사활동_명단_{target_act_id}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
        conn.close()
