import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import os
from datetime import datetime
import io
import re
import calendar

# PDF 파싱 라이브러리
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# --- 1. 기본 설정 및 DB 초기화 ---
st.set_page_config(
    page_title="GUC 봉사활동 신청 및 실적관리 시스템",
    page_icon="🤝",
    layout="wide"
)

CONTACT_INFO = "담당자 : 김나율 (031-980-8323)"

DEPT_ORDER = [
    "경영지원실", "기획평가팀", "인사총무팀", "혁신경영팀",
    "경영재정실", "재무회계1팀", "재무회계2팀",
    "윤리경영실", "청렴감사팀", "안전보건팀", "정보보안팀",
    "문화사업팀", "시민회관팀", "태산패밀리파크팀", "함상공원팀", "추모공원팀",
    "체육사업1실", "생활체육관팀", "풍무체육관팀", "고촌체육관팀",
    "체육사업2실", "주민편익시설팀", "문화회관팀", "양곡체육관팀",
    "환경사업실", "자원관리팀", "자원시설팀", "재활용사업팀",
    "교통사업실", "교통지원팀", "주차운영팀", "주차시설팀", "지하차도팀",
    "도시개발본부", "경제진흥실", "경제진흥1팀", "경제진흥2팀",
    "균형발전실", "균형발전1팀", "균형발전2팀",
    "전략사업실", "전략사업1팀", "전략사업2팀", "전략사업3팀",
    "기타/파견"
]

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
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    c.execute("SELECT value FROM settings WHERE key = 'admin_password'")
    if not c.fetchone():
        c.execute("INSERT INTO settings (key, value) VALUES ('admin_password', 'admin1234')")
    
    # 1. 단체 봉사활동 일감
    c.execute('''
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            deadline TEXT,
            location TEXT NOT NULL,
            category TEXT DEFAULT '환경정화 / 생태보전',
            hours REAL NOT NULL,
            max_capacity INTEGER NOT NULL,
            description TEXT,
            status TEXT DEFAULT '모집중'
        )
    ''')
    
    # 2. 단체 봉사활동 신청자
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
    
    # 3. 개인 1365 실적 기록 (5대 컬럼 포함)
    c.execute('''
        CREATE TABLE IF NOT EXISTS personal_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_name TEXT NOT NULL,
            dept TEXT NOT NULL,
            birthdate TEXT,
            v_date TEXT NOT NULL,
            v_title TEXT NOT NULL,
            v_category TEXT DEFAULT '일반봉사',
            v_hours REAL NOT NULL,
            v_org TEXT,
            uploaded_at TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# --- 헬퍼 함수 정의 ---
def get_admin_password():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'admin_password'")
    row = c.fetchone()
    conn.close()
    return row['value'] if row else "admin1234"

def update_admin_password(new_pw):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = 'admin_password'", (new_pw,))
    conn.commit()
    conn.close()

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

def extract_date_part(date_str):
    match = re.search(r'(\d{4}-\d{2}-\d{2})', str(date_str))
    return match.group(1) if match else None

def parse_korean_date(date_text):
    m = re.search(r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', str(date_text))
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m2 = re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', str(date_text))
    if m2:
        return f"{int(m2.group(1)):04d}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    return str(date_text).strip()

def parse_korean_hours(hour_text):
    m = re.search(r'(\d+)\s*시간(?:\s*(\d+)\s*분)?', str(hour_text))
    if m:
        h = float(m.group(1))
        mins = float(m.group(2)) if m.group(2) else 0.0
        return round(h + (mins / 60.0), 2)
    m2 = re.search(r'(\d+(?:\.\d+)?)\s*(?:시간|hr|H)?', str(hour_text))
    if m2:
        return float(m2.group(1))
    return 0.0

def lookup_known_dept(emp_name, birthdate=""):
    conn = get_db()
    c = conn.cursor()
    if birthdate:
        c.execute("SELECT dept FROM personal_records WHERE emp_name = ? AND birthdate = ? ORDER BY id DESC LIMIT 1", (emp_name, birthdate))
    else:
        c.execute("SELECT dept FROM personal_records WHERE emp_name = ? ORDER BY id DESC LIMIT 1", (emp_name,))
    res = c.fetchone()
    if res:
        conn.close()
        return res[0]
    
    if birthdate:
        c.execute("SELECT dept FROM applications WHERE name = ? AND birthdate = ? ORDER BY id DESC LIMIT 1", (emp_name, birthdate))
    else:
        c.execute("SELECT dept FROM applications WHERE name = ? ORDER BY id DESC LIMIT 1", (emp_name,))
    res2 = c.fetchone()
    conn.close()
    if res2:
        return res2[0]
    
    return "인사총무팀"

def parse_multi_1365_pdf(file_bytes):
    """
    [완전 개량된 다페이지 1365 통합 PDF 파서]
    - 4페이지 이상인 대용량 확인서(이덕재 등)에서 발급번호 및 인적사항 전역 추적[cite: 1]
    - 줄바꿈이나 공백이 섞인 '성 명:' 패턴 완벽 대응[cite: 1]
    """
    if PdfReader is None:
        return None, "pypdf 라이브러리가 필요합니다."
    
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        doc_info = {}
        active_doc_id = "DOC_DEFAULT"
        active_name = "미확인직원"
        active_birth = ""
        
        known_categories = [
            "환경·생태계보호", "환경 · 생태계보호", "환경정화", "주거환경", "생활편의",
            "문화·체육·예술·관광", "문화·체육", "문화 · 체육", "자원봉사 기본교육", "자원봉사기본교육",
            "보건·의료", "보건 · 의료", "지역안전·보호", "안전예방", "재난·재해", "재난 · 재해",
            "교육", "기타", "사회복지", "행정지원"
        ]
        
        date_re = re.compile(r'(\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}[-./]\d{1,2}[-./]\d{1,2})')
        hour_re = re.compile(r'(\d+)\s*시간(?:\s*(\d+)\s*분)?')
        
        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            
            # 발급번호 감지
            doc_id_match = re.search(r'발급번호\s*[:：]?\s*([0-9_]+)', page_text)
            if doc_id_match:
                active_doc_id = doc_id_match.group(1).strip()
                active_name = "미확인직원"
                active_birth = ""
            
            if active_doc_id not in doc_info:
                doc_info[active_doc_id] = {
                    "name": "",
                    "birthdate": "",
                    "records": []
                }
                
            # 성명 추출 (줄바꿈 허용)
            name_match = re.search(r'성[\s\n]*명[\s\n]*[:：]?\s*([가-힣]{2,5})', page_text)
            if name_match:
                active_name = name_match.group(1).strip()
                doc_info[active_doc_id]["name"] = active_name
            elif not doc_info[active_doc_id]["name"]:
                doc_info[active_doc_id]["name"] = active_name
                
            # 생년월일 추출
            birth_match = re.search(r'주민등록번호[\s\n]*[:：]?\s*(\d{6})', page_text)
            if birth_match:
                active_birth = format_birthdate(birth_match.group(1).strip())
                doc_info[active_doc_id]["birthdate"] = active_birth
            elif not doc_info[active_doc_id]["birthdate"]:
                doc_info[active_doc_id]["birthdate"] = active_birth

            # 실적 상세 테이블 파싱
            if "자원봉사 활동실적" in page_text or "활동기간" in page_text or re.search(r'\d{4}\s*년.*시간', page_text):
                norm_text = page_text.replace('\r', '\n')
                norm_text = re.sub(r'(\d{4}\s*년\s*\d{1,2}\s*월)\s*\n\s*(\d{1,2}\s*일)', r'\1 \2', norm_text)
                norm_text = re.sub(r'(\d{4}[-./]\d{1,2})[-./]\s*\n\s*(\d{1,2})', r'\1-\2', norm_text)
                
                raw_lines = [l.strip() for l in norm_text.split('\n') if l.strip()]
                
                i = 0
                while i < len(raw_lines):
                    line = raw_lines[i]
                    
                    if re.search(r'(활동기간\s*:\s*\d{4}|총\s*\d+\s*시간|외\s*\d+건|활동횟수\s*:)', line):
                        i += 1
                        continue
                        
                    d_m = date_re.search(line)
                    if d_m:
                        raw_d = d_m.group(1)
                        v_date = parse_korean_date(raw_d)
                        rest_line = line[d_m.end():].replace('|', ' ').strip()
                        
                        h_m = hour_re.search(rest_line)
                        v_hours = 0.0
                        tokens = []
                        
                        if h_m and not re.search(r'총\s*\d+시간', rest_line):
                            h_val = float(h_m.group(1))
                            m_val = float(h_m.group(2)) if h_m.group(2) else 0.0
                            v_hours = round(h_val + (m_val / 60.0), 2)
                            after_h = rest_line[h_m.end():].strip()
                            if after_h: tokens.append(after_h)
                        else:
                            if (i + 1) < len(raw_lines):
                                next_line_clean = raw_lines[i+1].replace('|', ' ').strip()
                                h_m2 = hour_re.search(next_line_clean)
                                if h_m2 and not re.search(r'총\s*\d+시간', next_line_clean):
                                    i += 1
                                    h_val = float(h_m2.group(1))
                                    m_val = float(h_m2.group(2)) if h_m2.group(2) else 0.0
                                    v_hours = round(h_val + (m_val / 60.0), 2)
                                    after_h2 = next_line_clean[h_m2.end():].strip()
                                    if after_h2: tokens.append(after_h2)
                                        
                        if v_hours > 0:
                            look = i + 1
                            while look < len(raw_lines):
                                curr_look = raw_lines[look].replace('|', ' ').strip()
                                if date_re.search(curr_look) or re.search(r'(발급번호|자원봉사활동\s*확인서|본\s*증명서는|담당자\s*:|제출용|1365\.go\.kr|활동기간\s*:)', curr_look):
                                    break
                                tokens.append(curr_look)
                                look += 1
                                if look - i > 6:
                                    break
                                    
                            i = look - 1
                            full_row_str = " ".join(tokens).strip()
                            
                            v_cat = "기타"
                            v_title = full_row_str
                            v_org = "1365 자원봉사센터"
                            
                            for cat in known_categories:
                                if cat in full_row_str:
                                    v_cat = cat
                                    parts = full_row_str.split(cat, 1)
                                    v_title = parts[1].strip() if len(parts) > 1 else full_row_str
                                    break
                                    
                            org_m = re.search(r'((?:경기도|인천광역시|서울특별시|제주특별자치도|[가-힣]+시|[가-힣]+구)?[가-힣\s()]+(?:자원봉사센터|종합자원봉사센|센터|도시공사|시청|구청|안심센터|복지관|혈액관리본부|실천운동본부))$', v_title)
                            if org_m:
                                v_org = org_m.group(1).strip()
                                v_title = v_title[:org_m.start()].strip()
                                
                            v_title = re.sub(r'\s+', ' ', v_title).strip() or "자원봉사활동"
                            
                            dup = any(r['date'] == v_date and r['title'] == v_title for r in doc_info[active_doc_id]["records"])
                            if not dup:
                                doc_info[active_doc_id]["records"].append({
                                    "date": v_date,
                                    "hours": v_hours,
                                    "category": v_cat,
                                    "title": v_title,
                                    "org": v_org
                                })
                    i += 1

        result = []
        for doc_id, p_data in doc_info.items():
            if p_data["records"]:
                p_name = p_data["name"] or "미확인직원"
                p_birth = p_data["birthdate"]
                auto_dept = lookup_known_dept(p_name, p_birth)
                result.append({
                    "name": p_name,
                    "birthdate": p_birth,
                    "default_dept": auto_dept,
                    "records": p_data["records"]
                })
                
        return result, None
    except Exception as e:
        return None, str(e)

def sort_by_dept(df):
    if df.empty or '소속부서' not in df.columns:
        if not df.empty and '순번' not in df.columns:
            df.insert(0, '순번', range(1, len(df) + 1))
        return df
        
    def get_dept_index(dept_name):
        d = str(dept_name).strip()
        if d in DEPT_ORDER: return DEPT_ORDER.index(d)
        for idx, target in enumerate(DEPT_ORDER):
            if target in d or d in target: return idx
        return len(DEPT_ORDER)
    
    df_sorted = df.copy()
    df_sorted['__dept_rank'] = df_sorted['소속부서'].apply(get_dept_index)
    sort_keys = ['__dept_rank']
    if '신청일시' in df_sorted.columns: sort_keys.append('신청일시')
    elif '활동기간' in df_sorted.columns: sort_keys.append('활동기간')
    elif '봉사일자' in df_sorted.columns: sort_keys.append('봉사일자')
    elif '성명' in df_sorted.columns: sort_keys.append('성명')
        
    df_sorted = df_sorted.sort_values(by=sort_keys).drop(columns=['__dept_rank'])
    
    if '순번' in df_sorted.columns:
        df_sorted['순번'] = range(1, len(df_sorted) + 1)
    else:
        df_sorted.insert(0, '순번', range(1, len(df_sorted) + 1))
        
    return df_sorted

def create_styled_excel(df, main_title, activity_date, hours_val=None, sheet_name="명단", is_attendance=False):
    df_ordered = sort_by_dept(df)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet(sheet_name)
        writer.sheets[sheet_name] = worksheet
        worksheet.set_paper(9)
        worksheet.set_portrait()
        worksheet.fit_to_pages(1, 0)
        
        t_fmt = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
        i_fmt = workbook.add_format({'bold': True, 'font_size': 10, 'font_color': '#333333', 'align': 'right', 'valign': 'vcenter'})
        h_fmt = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#EFEFEF', 'align': 'center', 'valign': 'vcenter', 'border': 1})
        c_fmt = workbook.add_format({'font_size': 9.5, 'align': 'center', 'valign': 'vcenter', 'border': 1})
        
        num_cols = len(df_ordered.columns)
        worksheet.merge_range(0, 0, 0, num_cols - 1, main_title, t_fmt)
        worksheet.set_row(0, 32)
        hours_str = f" ({hours_val}시간)" if hours_val else ""
        worksheet.merge_range(1, 0, 1, num_cols - 1, f"일시 : {activity_date}{hours_str}  |  {CONTACT_INFO}", i_fmt)
        worksheet.set_row(1, 18)
        
        worksheet.set_row(3, 24)
        for col_idx, col_name in enumerate(df_ordered.columns):
            worksheet.write(3, col_idx, col_name, h_fmt)
            
        for row_idx, row in enumerate(df_ordered.itertuples(index=False), start=4):
            worksheet.set_row(row_idx, 30 if is_attendance else 24)
            for col_idx, value in enumerate(row):
                worksheet.write(row_idx, col_idx, "" if pd.isna(value) else str(value), c_fmt)
                    
        for i, col in enumerate(df_ordered.columns):
            worksheet.set_column(i, i, max(len(str(col)) + 6, 12))
    return output.getvalue()

def create_personal_report_excel(summary_df, detail_df, cat_df, period_label):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        t_fmt = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
        d_fmt = workbook.add_format({'bold': True, 'font_size': 10, 'font_color': '#555555', 'align': 'right'})
        h_fmt = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#EFEFEF', 'align': 'center', 'valign': 'vcenter', 'border': 1})
        c_fmt = workbook.add_format({'font_size': 9.5, 'align': 'center', 'valign': 'vcenter', 'border': 1})
        
        ws1 = workbook.add_worksheet("활동실적_세부명세")
        writer.sheets["활동실적_세부명세"] = ws1
        ws1.set_paper(9)
        ws1.fit_to_pages(1, 0)
        
        detail_sorted = sort_by_dept(detail_df)
        ws1.merge_range(0, 0, 0, len(detail_sorted.columns) - 1, f"■ GUC 임직원 자원봉사 활동실적 세부 명세서 ({period_label})", t_fmt)
        ws1.set_row(0, 32)
        ws1.merge_range(1, 0, 1, len(detail_sorted.columns) - 1, f"출력기준 : {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  {CONTACT_INFO}", d_fmt)
        ws1.set_row(1, 18)
        
        ws1.set_row(3, 24)
        for c_idx, c_name in enumerate(detail_sorted.columns):
            ws1.write(3, c_idx, c_name, h_fmt)
        for r_idx, r_val in enumerate(detail_sorted.itertuples(index=False), start=4):
            ws1.set_row(r_idx, 24)
            for c_idx, val in enumerate(r_val):
                ws1.write(r_idx, c_idx, "" if pd.isna(val) else str(val), c_fmt)
        for i, col in enumerate(detail_sorted.columns):
            ws1.set_column(i, i, max(len(str(col)) + 6, 14))

        ws2 = workbook.add_worksheet("직원별_총괄요약")
        writer.sheets["직원별_총괄요약"] = ws2
        ws2.set_paper(9)
        ws2.fit_to_pages(1, 0)
        ws2.merge_range(0, 0, 0, len(summary_df.columns) - 1, f"GUC 임직원 자원봉사 실적 총괄표 ({period_label})", t_fmt)
        ws2.set_row(0, 32)
        ws2.merge_range(1, 0, 1, len(summary_df.columns) - 1, f"출력기준 : {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  {CONTACT_INFO}", d_fmt)
        ws2.set_row(1, 18)
        
        ws2.set_row(3, 24)
        for c_idx, c_name in enumerate(summary_df.columns):
            ws2.write(3, c_idx, c_name, h_fmt)
        for r_idx, r_val in enumerate(summary_df.itertuples(index=False), start=4):
            ws2.set_row(r_idx, 22)
            for c_idx, val in enumerate(r_val):
                ws2.write(r_idx, c_idx, "" if pd.isna(val) else str(val), c_fmt)
        for i, col in enumerate(summary_df.columns):
            ws2.set_column(i, i, max(len(str(col)) + 6, 14))

        if not cat_df.empty:
            ws3 = workbook.add_worksheet("분야별_통계")
            writer.sheets["분야별_통계"] = ws3
            ws3.set_paper(9)
            ws3.merge_range(0, 0, 0, len(cat_df.columns) - 1, f"분야별 자원봉사 실적 통계표 ({period_label})", t_fmt)
            ws3.set_row(0, 32)
            ws3.merge_range(1, 0, 1, len(cat_df.columns) - 1, f"출력기준 : {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  {CONTACT_INFO}", d_fmt)
            ws3.set_row(1, 18)
            ws3.set_row(3, 24)
            for c_idx, c_name in enumerate(cat_df.columns):
                ws3.write(3, c_idx, c_name, h_fmt)
            for r_idx, r_val in enumerate(cat_df.itertuples(index=False), start=4):
                ws3.set_row(r_idx, 22)
                for c_idx, val in enumerate(r_val):
                    ws3.write(r_idx, c_idx, "" if pd.isna(val) else str(val), c_fmt)
            for i, col in enumerate(cat_df.columns):
                ws3.set_column(i, i, max(len(str(col)) + 6, 14))

    return output.getvalue()

# --- 2. 사이드바 메뉴 ---
st.sidebar.title("🤝 GUC 봉사활동 포털")
menu_list = [
    "GUC 봉사활동 신청",
    "활동별 참여자 현황 및 본인 취소",
    "📄 1365 개인/통합 봉사확인서 등록 (PDF)",
    "관리자 모드"
]

if "menu_nav" not in st.session_state:
    st.session_state["menu_nav"] = "GUC 봉사활동 신청"

menu = st.sidebar.radio("메뉴 선택", menu_list, key="menu_nav")
st.sidebar.divider()
st.sidebar.caption(f"📞 **문의처**  \n{CONTACT_INFO}")

# --- 3. [직원용] 단체 봉사활동 신청 ---
if menu == "GUC 봉사활동 신청":
    st.title("🌱 GUC 봉사활동 신청")
    st.caption(f"봉사활동 일정을 확인하고 신청서를 작성해주세요. ({CONTACT_INFO})")

    if "last_applied" in st.session_state and st.session_state["last_applied"]:
        info = st.session_state["last_applied"]
        with st.container(border=True):
            st.success(f"🎉 **{info['name']}님의 봉사활동 신청이 정상적으로 완료되었습니다!**")
            st.write(f"📌 **신청 활동:** {info['act_title']} | 🏢 **소속:** {info['dept']} | 🔢 **상태:** `{info['status_msg']}`")
            if st.button("👉 신청 내역 확인하러 가기", type="primary"):
                st.session_state["menu_nav"] = "활동별 참여자 현황 및 본인 취소"
                st.session_state["selected_view_act_id"] = None
                st.session_state["last_applied"] = None
                st.rerun()

    conn = get_db()
    activities_df = pd.read_sql_query("SELECT * FROM activities ORDER BY date ASC", conn)
    now_str_cal = datetime.now().strftime("%Y-%m-%d %H:%M")
    today_date_str = datetime.now().strftime("%Y-%m-%d")
    
    st.subheader("📅 봉사활동 월별 캘린더")
    today = datetime.now()
    if "cal_year" not in st.session_state: st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state: st.session_state["cal_month"] = today.month

    col_prev, col_m, col_next = st.columns([1, 4, 1])
    with col_prev:
        if st.button("◀ 이전 달", use_container_width=True):
            if st.session_state["cal_month"] == 1:
                st.session_state["cal_month"] = 12
                st.session_state["cal_year"] -= 1
            else:
                st.session_state["cal_month"] -= 1
            st.rerun()
    with col_m:
        st.markdown(f"<h4 style='text-align: center; margin: 0; color:#1e293b;'>🗓️ {st.session_state['cal_year']}년 {st.session_state['cal_month']}월</h4>", unsafe_allow_html=True)
    with col_next:
        if st.button("다음 달 ▶", use_container_width=True):
            if st.session_state["cal_month"] == 12:
                st.session_state["cal_month"] = 1
                st.session_state["cal_year"] += 1
            else:
                st.session_state["cal_month"] += 1
            st.rerun()

    act_by_date = {}
    month_act_options = {}
    for _, act in activities_df.iterrows():
        d_part = extract_date_part(act['date'])
        if d_part:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (act['id'],))
            cnt = c.fetchone()[0]
            st_val = "모집마감" if (act['status'] == "모집중" and act['deadline'] and act['deadline'] < now_str_cal) else act['status']
            if d_part not in act_by_date: act_by_date[d_part] = []
            act_by_date[d_part].append({"id": act['id'], "title": act['title'], "status": st_val, "count": cnt, "max": act['max_capacity']})
            if d_part[:7] == f"{st.session_state['cal_year']:04d}-{st.session_state['cal_month']:02d}":
                month_act_options[f"[{st_val}] [{act['date']}] {act['title']}"] = act['id']

    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(st.session_state["cal_year"], st.session_state["cal_month"])
    table_rows = []
    for week in month_days:
        tds = []
        for day_idx, day_num in enumerate(week):
            if day_num != 0:
                date_key = f"{st.session_state['cal_year']:04d}-{st.session_state['cal_month']:02d}-{day_num:02d}"
                has_events = date_key in act_by_date
                day_color = "#dc2626" if day_idx == 0 else ("#2563eb" if day_idx == 6 else "#1e293b")
                cell_bg = "#f0fdf4" if has_events else "#ffffff"
                event_items = []
                if has_events:
                    for ev in act_by_date[date_key]:
                        b_color = "#16a34a" if ev['status'] == "모집중" else ("#dc2626" if ev['status'] == "모집마감" else "#475569")
                        event_items.append(f'<div style="background:#ffffff; border-left:3px solid {b_color}; border:1px solid #e2e8f0; border-radius:4px; padding:3px 5px; margin-top:3px; font-size:11px; line-height:1.2;"><span style="color:{b_color}; font-weight:bold;">[{ev["status"]}]</span> <strong style="color:#0f172a;">{ev["title"]}</strong><br><span style="color:#64748b; font-size:10px;">({ev["count"]}/{ev["max"]}명)</span></div>')
                tds.append(f'<td style="width:14.28%; height:80px; vertical-align:top; background-color:{cell_bg}; border:1px solid #cbd5e1; padding:4px;"><div style="font-weight:bold; font-size:12px; color:{day_color};">{day_num}</div>{"".join(event_items)}</td>')
            else:
                tds.append('<td style="width:14.28%; height:80px; background-color:#f8fafc; border:1px solid #e2e8f0;"></td>')
        table_rows.append(f"<tr>{''.join(tds)}</tr>")

    full_calendar_html = f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:0;}}table{{width:100%;border-collapse:collapse;border:1px solid #cbd5e1;border-radius:6px;overflow:hidden;}}th{{background-color:#f1f5f9;padding:6px;font-size:13px;font-weight:bold;border:1px solid #cbd5e1;text-align:center;}}</style></head><body><table><thead><tr><th style="color:#dc2626;">일</th><th>월</th><th>화</th><th>수</th><th>목</th><th>금</th><th style="color:#2563eb;">토</th></tr></thead><tbody>{"".join(table_rows)}</tbody></table></body></html>'
    components.html(full_calendar_html, height=80 * len(month_days) + 60, scrolling=False)
    
    if month_act_options:
        col_q1, col_q2 = st.columns([4, 1])
        with col_q1: quick_selected = st.selectbox("🔍 이번 달 활동의 신청 현황 / 참여자 명단 바로보기", list(month_act_options.keys()))
        with col_q2:
            st.write(""); st.write("")
            if st.button("현황 페이지 이동 👉", type="secondary", use_container_width=True):
                st.session_state["selected_view_act_id"] = month_act_options[quick_selected]
                st.session_state["menu_nav"] = "활동별 참여자 현황 및 본인 취소"
                st.rerun()

    st.divider()
    st.subheader("📢 향후 봉사활동 목록 및 진행 현황 (미도래 전체 일정)")
    upcoming_acts = [act for _, act in activities_df.iterrows() if not extract_date_part(act['date']) or extract_date_part(act['date']) >= today_date_str or act['status'] == "모집중"]

    if not upcoming_acts:
        st.info("현재 예정된 향후(미도래) 봉사활동 일감이 없습니다.")
    else:
        act_options = {}
        for act in upcoming_acts:
            act_id = act['id']
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (act_id,))
            current_count = c.fetchone()[0]
            max_cap = act['max_capacity']
            remain = max_cap - current_count
            is_expired = bool(act['deadline'] and act['deadline'] < now_str_cal)
            current_status = "모집마감" if (act['status'] == "모집중" and is_expired) else act['status']

            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    status_badge = "🟢 모집중" if current_status == "모집중" else ("🔴 모집마감" if current_status == "모집마감" else "⚫ 활동종료")
                    st.subheader(f"{act['title']} `[{status_badge}]`")
                    st.write(f"📅 **일시:** {act['date']} | 📍 **장소:** {act['location']} | 🏷️ **분야:** {act.get('category', '환경정화/생태')} | ⏱️ **인정시간:** {act['hours']}시간")
                    if act['description']: st.write(f"📝 {act['description']}")
                with col2:
                    if current_status == "모집중":
                        st.metric("신청 현황", f"{current_count} / {max_cap} 명", delta=f"잔여 {remain}명" if remain > 0 else f"대기 {abs(remain)}명")
                    else:
                        st.metric("신청 인원", f"{current_count} / {max_cap} 명")
                        st.error(current_status)

            if current_status == "모집중":
                label = f"[{act['date']}] {act['title']} (잔여 {remain}명)" if remain > 0 else f"[{act['date']}] {act['title']} [대기접수]"
                act_options[label] = (act_id, max_cap, remain, act['title'])

        st.divider()
        st.subheader("📋 참가 신청서 작성")
        if not act_options:
            st.warning("현재 신청 가능한 봉사활동이 없습니다.")
        else:
            with st.form("apply_form", clear_on_submit=True):
                selected_act_label = st.selectbox("신청할 봉사활동 선택 *", list(act_options.keys()))
                name = st.text_input("1. 성명 *", placeholder="예: 홍길동")
                dept = st.selectbox("2. 소속 부서 선택 *", DEPT_ORDER)
                birthdate = st.text_input("3. 생년월일 (YYYY-MM-DD) *", placeholder="예: 1980-06-02")
                phone = st.text_input("4. 휴대폰 번호 *", placeholder="예: 010-1234-5678")
                v1365_id = st.text_input("5. 1365 ID (선택)", placeholder="1365 아이디")
                
                if st.form_submit_button("봉사활동 신청하기", use_container_width=True):
                    selected_id, max_cap, remain, act_title = act_options[selected_act_label]
                    if not (name.strip() and dept.strip() and birthdate.strip() and phone.strip()):
                        st.warning("필수 정보를 모두 입력해주세요.")
                    else:
                        formatted_birth = format_birthdate(birthdate)
                        clean_phone = phone.strip()
                        c = conn.cursor()
                        c.execute("SELECT id FROM applications WHERE activity_id = ? AND name = ? AND birthdate = ?", (selected_id, name.strip(), formatted_birth))
                        if c.fetchone():
                            st.error("이미 신청하신 봉사활동입니다.")
                        else:
                            now_apply = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            c.execute('''
                                INSERT INTO applications (activity_id, name, dept, birthdate, phone, v1365_id, applied_at, attendance)
                                VALUES (?, ?, ?, ?, ?, ?, ?, '대기')
                            ''', (selected_id, name.strip(), dept.strip(), formatted_birth, clean_phone, v1365_id.strip(), now_apply))
                            conn.commit()
                            c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (selected_id,))
                            total_now = c.fetchone()[0]
                            st.session_state["last_applied"] = {
                                "name": name.strip(), "dept": dept.strip(), "act_title": act_title,
                                "status_msg": f"정원 내 확정 ({total_now}번)" if total_now <= max_cap else f"신청 대기 ({total_now - max_cap}번)"
                            }
                            st.balloons()
                            st.rerun()
    conn.close()

# --- 4. [직원용] 활동별 참여자 현황 ---
elif menu == "활동별 참여자 현황 및 본인 취소":
    st.title("👥 봉사활동별 참여자 명단 및 신청 취소")
    conn = get_db()
    acts = pd.read_sql_query("SELECT id, title, date, location, hours, max_capacity, status FROM activities ORDER BY date DESC", conn)
    
    if acts.empty:
        st.info("등록된 봉사활동이 없습니다.")
    else:
        act_labels = []
        act_id_map = {}
        target_index = 0
        selected_id_from_cal = st.session_state.get("selected_view_act_id", None)
        for idx, row in acts.iterrows():
            lbl = f"[{row['status']}] [{row['date']}] {row['title']}"
            act_labels.append(lbl)
            act_id_map[lbl] = row['id']
            if selected_id_from_cal and row['id'] == selected_id_from_cal:
                target_index = idx

        selected_act_label = st.selectbox("조회할 봉사활동을 선택하세요", act_labels, index=target_index)
        target_act_id = act_id_map[selected_act_label]
        act_info = acts[acts['id'] == target_act_id].iloc[0]
        max_cap = act_info['max_capacity']
        
        st.write(f"📍 **장소:** {act_info['location']} | ⏱️ **인정시간:** {act_info['hours']}시간 | 🎯 **정원:** {max_cap}명 | 📌 **상태:** `{act_info['status']}`")
        apps_df = pd.read_sql_query("SELECT id, name, dept, birthdate, phone, applied_at, attendance FROM applications WHERE activity_id = ? ORDER BY id ASC", conn, params=(target_act_id,))

        st.subheader("📋 실시간 신청자 및 대기자 명단")
        if apps_df.empty:
            st.info("아직 신청자가 없습니다.")
        else:
            apps_df.insert(0, '구분', ["정원내 확정" if i < max_cap else f"대기 {i - max_cap + 1}번" for i in range(len(apps_df))])
            apps_df.insert(1, '순번', range(1, len(apps_df) + 1))
            display_df = apps_df.copy()
            display_df['생년월일'] = display_df['birthdate'].apply(mask_birth)
            display_df['휴대폰번호'] = display_df['phone'].apply(mask_phone)
            view_cols = ['순번', '구분', 'name', 'dept', '생년월일', '휴대폰번호', 'applied_at']
            if act_info['status'] == "활동종료": view_cols.append('attendance')
            display_df = display_df[view_cols]
            display_df.columns = ['순번', '구분', '성명', '소속부서', '생년월일', '연락처', '신청일시'] + (['참석여부'] if act_info['status'] == "활동종료" else [])
            st.dataframe(display_df, use_container_width=True)

        st.divider()
        st.subheader("❌ 내 신청 직접 취소하기")
        with st.form("cancel_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1: c_name = st.text_input("성명", placeholder="홍길동")
            with c2: c_birth = st.text_input("생년월일", placeholder="1980-06-02")
            with c3: c_phone = st.text_input("휴대폰 번호", placeholder="010-1234-5678")
            if st.form_submit_button("신청 취소하기", type="primary", use_container_width=True):
                if c_name.strip() and c_birth.strip() and c_phone.strip():
                    fmt_cbirth = format_birthdate(c_birth)
                    c = conn.cursor()
                    c.execute("SELECT id FROM applications WHERE activity_id = ? AND name = ? AND birthdate = ?", (target_act_id, c_name.strip(), fmt_cbirth, c_phone.strip()))
                    matched = c.fetchone()
                    if matched:
                        c.execute("DELETE FROM applications WHERE id = ?", (matched[0],))
                        conn.commit()
                        st.success(f"{c_name}님의 봉사활동 신청이 정상 취소되었습니다.")
                        st.rerun()
                    else:
                        st.error("일치하는 신청 내역이 없습니다.")
    conn.close()

# --- 5. [직원용] 1365 개인/다인원 통합 확인서 PDF 업로드 & 삭제 ---
elif menu == "📄 1365 개인/통합 봉사확인서 등록 (PDF)":
    st.title("📄 1365 봉사활동 확인서 등록 및 관리")
    st.caption("1365 자원봉사포털에서 발급받은 '자원봉사 실적 확인서(PDF)'를 업로드하세요. **(1페이지 요약 및 2페이지 이후 상세 활동실적이 모두 자동 추출됩니다.)**")

    if "last_pdf_registered" in st.session_state and st.session_state["last_pdf_registered"]:
        reg_info = st.session_state["last_pdf_registered"]
        with st.container(border=True):
            st.success(f"🎉 **{reg_info['msg']}**")
            st.info("💡 등록된 실적은 아래 **[내 등록 실적 조회 및 삭제]** 또는 관리자 대시보드에서 즉시 확인하실 수 있습니다.")
        st.session_state["last_pdf_registered"] = None

    tab_upload, tab_manage = st.tabs(["📤 확인서 PDF 파일 업로드 및 자동분석", "🔍 내 등록 실적 조회 및 잘못 올린 실적 삭제"])
    
    with tab_upload:
        with st.container(border=True):
            st.subheader("1. 1365 실적확인서 PDF 업로드")
            st.caption("ℹ️ 성명, 주민등록번호 기반 생년월일, 활동기간, 봉사시간, 분야, 봉사내용, 관할센터/기관명 등 5대 항목이 자동으로 파싱됩니다.")
            uploaded_pdf = st.file_uploader("1365 실적확인서 PDF 파일을 선택하세요 (단일/다인원 통합 PDF 모두 지원)", type=["pdf"])
            
            if uploaded_pdf is not None:
                parsed_persons, err = parse_multi_1365_pdf(uploaded_pdf.getvalue())
                if err:
                    st.error(f"PDF 파싱 실패: {err}")
                elif not parsed_persons:
                    st.warning("PDF에서 봉사활동 실적 내역을 찾을 수 없습니다. 올바른 1365 실적확인서 파일인지 확인해주세요.")
                else:
                    st.success(f"✅ **총 {len(parsed_persons)}명**의 봉사활동 실적 상세 데이터가 정상 분석되었습니다.")
                    st.divider()
                    
                    st.subheader("2. 추출된 인원별 실적 확인 및 부서 일괄/개별 지정")
                    
                    for idx, p in enumerate(parsed_persons):
                        sb_key = f"dept_select_box_{idx}"
                        if sb_key not in st.session_state:
                            st.session_state[sb_key] = p['default_dept']
                    
                    with st.container(border=True):
                        st.write("##### ⚡ 선택 인원 부서 일괄 변경")
                        col_b1, col_b2, col_b3 = st.columns([1.5, 2.5, 2])
                        with col_b1:
                            col_sel_all, col_desel_all = st.columns(2)
                            with col_sel_all:
                                if st.button("☑️ 전체선택", use_container_width=True):
                                    for idx in range(len(parsed_persons)):
                                        st.session_state[f"chk_person_{idx}"] = True
                                    st.rerun()
                            with col_desel_all:
                                if st.button("⬜ 전체해제", use_container_width=True):
                                    for idx in range(len(parsed_persons)):
                                        st.session_state[f"chk_person_{idx}"] = False
                                    st.rerun()
                        with col_b2:
                            bulk_target_dept = st.selectbox("일괄 적용할 부서 선택", DEPT_ORDER, key="bulk_dept_choice")
                        with col_b3:
                            if st.button("🚀 선택한 사람 부서 일괄 변경", type="secondary", use_container_width=True):
                                changed_count = 0
                                for idx in range(len(parsed_persons)):
                                    if st.session_state.get(f"chk_person_{idx}", False):
                                        st.session_state[f"dept_select_box_{idx}"] = bulk_target_dept
                                        changed_count += 1
                                if changed_count > 0:
                                    st.success(f"선택하신 {changed_count}명의 소속 부서가 '{bulk_target_dept}'(으)로 일괄 변경되었습니다!")
                                    st.rerun()
                                else:
                                    st.warning("부서를 변경할 직원의 체크박스를 1명 이상 선택해주세요.")

                    st.write("")
                    total_records_count = 0
                    for idx, p in enumerate(parsed_persons):
                        total_records_count += len(p['records'])
                        current_person_dept = st.session_state.get(f"dept_select_box_{idx}", p['default_dept'])
                        
                        with st.expander(f"👤 {idx+1}. {p['name']} (생년월일: {p['birthdate'] or '미확인'}) - 현재 소속: [{current_person_dept}] (상세 실적 총 {len(p['records'])}건 / {sum(r['hours'] for r in p['records']):.1f}시간)", expanded=True):
                            c_chk, c_dept, c_tbl = st.columns([0.8, 1.8, 4.4])
                            with c_chk:
                                st.checkbox("선택", key=f"chk_person_{idx}")
                            with c_dept:
                                st.selectbox(f"소속 부서 개별 변경", DEPT_ORDER, key=f"dept_select_box_{idx}")
                            with c_tbl:
                                rec_df = pd.DataFrame(p['records'])
                                rec_df = rec_df[['date', 'hours', 'category', 'title', 'org']]
                                rec_df.columns = ["활동기간(일자)", "봉사시간(h)", "분야", "봉사내용", "관할센터 / 실적등록기관"]
                                st.dataframe(rec_df, use_container_width=True)

                    st.write("")
                    col_save1, col_save2 = st.columns([2, 1])
                    with col_save1:
                        if st.button(f"💾 총 {len(parsed_persons)}명 (실적 {total_records_count}건) 전체 일괄 시스템에 등록하기", type="primary", use_container_width=True):
                            conn = get_db()
                            c = conn.cursor()
                            now_upload = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            total_inserted = 0
                            names_summary = []
                            
                            for idx, p in enumerate(parsed_persons):
                                p_dept = st.session_state.get(f"dept_select_box_{idx}", p['default_dept'])
                                c.execute("DELETE FROM personal_records WHERE emp_name = ?", (p['name'],))
                                
                                p_inserted = 0
                                for r in p['records']:
                                    c.execute('''
                                        INSERT INTO personal_records (emp_name, dept, birthdate, v_date, v_title, v_category, v_hours, v_org, uploaded_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (p['name'], p_dept, p['birthdate'], r['date'], r['title'], r['category'], r['hours'], r['org'], now_upload))
                                    p_inserted += 1
                                    
                                total_inserted += p_inserted
                                names_summary.append(f"{p['name']}({p_dept})")
                            
                            conn.commit()
                            conn.close()
                            
                            for idx in range(len(parsed_persons)):
                                if f"dept_select_box_{idx}" in st.session_state: del st.session_state[f"dept_select_box_{idx}"]
                                if f"chk_person_{idx}" in st.session_state: del st.session_state[f"chk_person_{idx}"]
                                
                            st.session_state["last_pdf_registered"] = {
                                "msg": f"총 {len(parsed_persons)}명 ({', '.join(names_summary)})의 세부 실적 총 {total_inserted}건이 정상 등록되었습니다!"
                            }
                            st.balloons()
                            st.rerun()

                    with col_save2:
                        if st.button("🧹 기존 등록실적 전체 삭제 후 새로등록", type="secondary", use_container_width=True):
                            conn = get_db()
                            c = conn.cursor()
                            c.execute("DELETE FROM personal_records")
                            now_upload = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            total_inserted = 0
                            for idx, p in enumerate(parsed_persons):
                                p_dept = st.session_state.get(f"dept_select_box_{idx}", p['default_dept'])
                                for r in p['records']:
                                    c.execute('''
                                        INSERT INTO personal_records (emp_name, dept, birthdate, v_date, v_title, v_category, v_hours, v_org, uploaded_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (p['name'], p_dept, p['birthdate'], r['date'], r['title'], r['category'], r['hours'], r['org'], now_upload))
                                    total_inserted += 1
                            conn.commit()
                            conn.close()
                            st.success("기존 데이터가 깨끗이 초기화되고 새 실적이 등록되었습니다!")
                            st.rerun()

    with tab_manage:
        with st.container(border=True):
            st.subheader("🔍 내 등록 실적 조회 및 잘못 올린 실적 삭제")
            st.caption("성명을 입력하여 본인의 세부 실적을 조회하고, 잘못 등록된 항목을 우측 [삭제] 버튼으로 취소할 수 있습니다.")
            
            q_name = st.text_input("성명 입력", placeholder="홍길동", key="my_rec_name")
            if q_name.strip():
                conn = get_db()
                my_df = pd.read_sql_query("""
                    SELECT id, emp_name AS 성명, dept AS 소속부서, birthdate AS 생년월일,
                           v_date AS 활동기간, v_hours AS 봉사시간, v_category AS 분야,
                           v_title AS 봉사내용, v_org AS 관할센터_실적등록기관, uploaded_at AS 등록일시
                    FROM personal_records
                    WHERE emp_name = ?
                    ORDER BY v_date DESC
                """, conn, params=(q_name.strip(),))
                
                if my_df.empty:
                    st.info(f"'{q_name}' 님의 등록된 개인 봉사활동 실적이 없습니다.")
                else:
                    total_my_hrs = my_df['봉사시간'].sum()
                    m1, m2 = st.columns(2)
                    with m1: st.metric(label="누적 봉사 실적", value=f"{round(total_my_hrs, 1)} 시간")
                    with m2: st.metric(label="총 등록 건수", value=f"{len(my_df)} 건")
                    
                    st.write("##### 📋 세부 실적 목록 (개별 삭제 가능)")
                    for _, row in my_df.iterrows():
                        with st.container(border=True):
                            c_info, c_del = st.columns([5, 1])
                            with c_info:
                                st.write(f"📅 **{row['활동기간']}** | **[{row['분야']}] {row['봉사내용']}** (`{row['봉사시간']}시간`)")
                                st.caption(f"소속: {row['소속부서']} | 관할센터/기관: {row['관할센터_실적등록기관']} | 등록일시: {row['등록일시']}")
                            with c_del:
                                st.write("")
                                if st.button("🗑️ 삭제", key=f"del_prec_{row['id']}"):
                                    c = conn.cursor()
                                    c.execute("DELETE FROM personal_records WHERE id = ?", (row['id'],))
                                    conn.commit()
                                    st.warning(f"'{row['봉사내용']}' 실적이 삭제되었습니다.")
                                    st.rerun()
                conn.close()

# --- 6. [관리자용] 관리자 대시보드 ---
elif menu == "관리자 모드":
    st.title("🛠️ 관리자 대시보드")
    admin_password = st.sidebar.text_input("관리자 비밀번호", type="password")
    current_saved_pw = get_admin_password()
    
    if "pw_changed_notice" in st.session_state and st.session_state["pw_changed_notice"]:
        st.success("✅ **관리자 비밀번호가 성공적으로 변경되었습니다!**")
        st.session_state["pw_changed_notice"] = False
    
    if admin_password != current_saved_pw:
        st.warning("사이드바에 올바른 관리자 비밀번호를 입력해주세요.")
    else:
        admin_section = st.radio(
            "관리 메뉴 선택",
            [
                "📊 [1365 실적 통계 & 직원별 이력]",
                "🗓️ [사내 단체 봉사활동 운영]",
                "⚙️ [시스템 관리]"
            ],
            horizontal=True,
            label_visibility="collapsed"
        )
        st.write("")
        conn = get_db()

        # =========================================================
        # 1구역: 1365 실적 통계 분석 및 개개인별 이력 명세
        # =========================================================
        if admin_section == "📊 [1365 실적 통계 & 직원별 이력]":
            tab_stat1, tab_stat2 = st.tabs([
                "📈 [실적 총괄 분석 & 1365 전체 세부내역]",
                "👤 [직원별 상세 이력] 개인별 활동기간·분야·내용·기관"
            ])
            
            with tab_stat1:
                st.subheader("📈 GUC 임직원 자원봉사 실적 총괄 분석 & 활동실적 세부내역")
                st.caption("1365 확인서 데이터를 바탕으로 총 봉사시간, 참여율, 1인당 봉사시간, 분야별 실적 및 **전체 세부 활동실적**을 확인합니다.")
                
                c_tmp = conn.cursor()
                c_tmp.execute("SELECT DISTINCT SUBSTR(v_date, 1, 4) FROM personal_records WHERE v_date IS NOT NULL AND v_date != ''")
                db_years = [r[0] for r in c_tmp.fetchall() if r[0] and r[0].isdigit()]
                
                available_years = ["전체 연도"] + sorted(list(set(db_years + ["2026", "2025", "2024"])), reverse=True)
                available_year_labels = [f"{y}년" if y != "전체 연도" else y for y in available_years]
                def_idx = available_year_labels.index("2025년") if "2025년" in available_year_labels else 0

                col_f1, col_f2, col_f3 = st.columns([1.2, 1.5, 1.2])
                with col_f1:
                    dash_year_lbl = st.selectbox("집계 연도 선택", available_year_labels, index=def_idx, key="dash_year_sel_v5")
                with col_f2:
                    dash_type = st.selectbox("집계 기간 구분", ["연간 전체", "상반기 (1월 ~ 6월)", "하반기 (7월 ~ 12월)", "월별 선택"], key="dash_type_sel_v5")
                selected_dash_month = None
                with col_f3:
                    if dash_type == "월별 선택":
                        selected_dash_month = st.selectbox("집계할 월 선택", [f"{m}월" for m in range(1, 13)], index=datetime.now().month - 1, key="dash_month_sel_v5")

                w_list, w_params = [], []
                if dash_year_lbl != "전체 연도":
                    y_num = dash_year_lbl.replace("년", "")
                    if dash_type == "상반기 (1월 ~ 6월)":
                        w_list.append("v_date >= ? AND v_date <= ?")
                        w_params.extend([f"{y_num}-01-01", f"{y_num}-06-30"])
                        dash_period_txt = f"{y_num}년 상반기"
                    elif dash_type == "하반기 (7월 ~ 12월)":
                        w_list.append("v_date >= ? AND v_date <= ?")
                        w_params.extend([f"{y_num}-07-01", f"{y_num}-12-31"])
                        dash_period_txt = f"{y_num}년 하반기"
                    elif dash_type == "월별 선택" and selected_dash_month:
                        m_val = int(selected_dash_month.replace("월", ""))
                        last_d = calendar.monthrange(int(y_num), m_val)[1]
                        w_list.append("v_date >= ? AND v_date <= ?")
                        w_params.extend([f"{y_num}-{m_val:02d}-01", f"{y_num}-{m_val:02d}-{last_d:02d}"])
                        dash_period_txt = f"{y_num}년 {selected_dash_month}"
                    else:
                        w_list.append("v_date >= ? AND v_date <= ?")
                        w_params.extend([f"{y_num}-01-01", f"{y_num}-12-31"])
                        dash_period_txt = f"{y_num}년 연간"
                else:
                    dash_period_txt = "전체 기간"

                w_sql = f"WHERE {' AND '.join(w_list)}" if w_list else ""
                
                dash_df = pd.read_sql_query(f"""
                    SELECT id, emp_name AS 성명, dept AS 소속부서, birthdate AS 생년월일,
                           v_date AS 활동기간, v_hours AS 봉사시간, v_category AS 분야,
                           v_title AS 봉사내용, v_org AS 관할센터_실적등록기관, uploaded_at AS 등록일시
                FROM personal_records {w_sql}
                ORDER BY v_date DESC
            """, conn, params=w_params)

                if dash_df.empty:
                    st.info(f"선택하신 기간({dash_period_txt})에 등록된 봉사활동 실적 데이터가 없습니다. 상단 연도 선택에서 다른 기간을 선택하거나 확인서 PDF를 먼저 등록해주세요.")
                else:
                    total_hours_val = dash_df['봉사시간'].sum()
                    unique_participants = dash_df['성명'].nunique()
                    total_cases_count = len(dash_df)
                    avg_hours_per_person = total_hours_val / max(1, unique_participants)
                    total_company_staff = 250
                    participation_rate = (unique_participants / total_company_staff) * 100

                    m1, m2, m3, m4, m5 = st.columns(5)
                    with m1: st.metric("연 누적 봉사시간", f"{round(total_hours_val, 1)} 시간", delta="합산 실적")
                    with m2: st.metric("참여 임직원 수", f"{unique_participants} 명")
                    with m3: st.metric("1인당 평균 봉사시간", f"{round(avg_hours_per_person, 1)} 시간")
                    with m4: st.metric("임직원 참여율", f"{round(participation_rate, 1)} %")
                    with m5: st.metric("총 활동 건수", f"{total_cases_count} 건")

                    st.divider()
                    
                    col_cat1, col_cat2 = st.columns([1.2, 1])
                    with col_cat1:
                        st.write(f"##### 🏷️ 분야별 봉사활동 실적 현황 ({dash_period_txt})")
                        cat_summary = dash_df.groupby('분야').agg(
                            총봉사시간=('봉사시간', 'sum'),
                            활동건수=('봉사시간', 'count'),
                            참여인원=('성명', 'nunique')
                        ).reset_index()
                        cat_summary['총봉사시간'] = cat_summary['총봉사시간'].round(1)
                        cat_summary['시간_비중(%)'] = ((cat_summary['총봉사시간'] / total_hours_val) * 100).round(1)
                        cat_summary = cat_summary.sort_values(by='총봉사시간', ascending=False)
                        cat_summary.insert(0, '순위', range(1, len(cat_summary) + 1))
                        st.dataframe(cat_summary, use_container_width=True)

                    with col_cat2:
                        st.write(f"##### 🏢 부서별 봉사 실적 요약 ({dash_period_txt})")
                        dept_summary = dash_df.groupby('소속부서').agg(
                            총봉사시간=('봉사시간', 'sum'),
                            참여인원=('성명', 'nunique'),
                            활동건수=('봉사시간', 'count')
                        ).reset_index()
                        dept_summary['총봉사시간'] = dept_summary['총봉사시간'].round(1)
                        dept_summary = sort_by_dept(dept_summary)
                        st.dataframe(dept_summary, use_container_width=True)

                    st.divider()
                    st.write(f"### ■ 자원봉사 활동실적 세부 명세서 ({dash_period_txt} - 총 {len(dash_df)}건)")
                    st.caption("확인서 PDF 양식과 100% 동일하게 **활동기간, 봉사시간, 분야, 봉사내용, 관할센터/실적등록기관**이 직원별로 빠짐없이 출력됩니다.")
                    
                    display_detail_df = dash_df.copy()
                    display_detail_df = sort_by_dept(display_detail_df)
                    
                    view_cols = ['순번', '성명', '소속부서', '활동기간', '봉사시간', '분야', '봉사내용', '관할센터_실적등록기관']
                    final_view_df = display_detail_df[[c for c in view_cols if c in display_detail_df.columns]]
                    st.dataframe(final_view_df, use_container_width=True)

                    user_summary = dash_df.groupby(['성명', '소속부서', '생년월일']).agg(
                        총봉사시간=('봉사시간', 'sum'),
                        참여건수=('봉사시간', 'count'),
                        최근활동일=('활동기간', 'max')
                    ).reset_index()
                    user_summary = sort_by_dept(user_summary)
                    user_summary['총봉사시간'] = user_summary['총봉사시간'].round(1)

                    p_excel_bytes = create_personal_report_excel(user_summary, final_view_df, cat_summary, dash_period_txt)
                    st.download_button(
                        label=f"📥 [{dash_period_txt} 자원봉사 활동실적 세부명세서 및 총괄표] 엑셀 다운로드",
                        data=p_excel_bytes,
                        file_name=f"GUC_자원봉사활동실적_세부명세서_{dash_period_txt}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        type="primary"
                    )

                    st.divider()
                    st.subheader("🗑️ 잘못 등록된 실적 관리자 선택 삭제")
                    del_tab1, del_tab2 = st.tabs(["👥 직원별 전체 실적 일괄 삭제", "📄 개별 실적 건별 체크박스 삭제"])
                    
                    with del_tab1:
                        col_d_all1, col_d_all2 = st.columns([1, 4])
                        with col_d_all1:
                            if st.button("☑️ 직원 전체선택", key="btn_del_emp_all"):
                                for idx in range(len(user_summary)): st.session_state[f"chk_del_emp_{idx}"] = True
                                st.rerun()
                        with col_d_all2:
                            if st.button("⬜ 직원 전체해제", key="btn_del_emp_none"):
                                for idx in range(len(user_summary)): st.session_state[f"chk_del_emp_{idx}"] = False
                                st.rerun()
                        
                        selected_emp_to_delete = []
                        for idx, u_row in user_summary.iterrows():
                            c_chk_emp, c_desc_emp = st.columns([0.8, 6.2])
                            with c_chk_emp:
                                if st.checkbox("선택", key=f"chk_del_emp_{idx}"):
                                    selected_emp_to_delete.append((u_row['성명'], u_row['생년월일']))
                            with c_desc_emp:
                                st.write(f"**{u_row['성명']}** ({u_row['소속부서']} / {u_row['생년월일']}) — 총 **{u_row['참여건수']}건** / **{u_row['총봉사시간']}시간**")
                        
                        if st.button(f"🗑️ 선택한 직원(총 {len(selected_emp_to_delete)}명)의 모든 봉사 실적 일괄 삭제", type="primary", key="btn_bulk_del_emp_submit"):
                            if not selected_emp_to_delete:
                                st.warning("삭제할 직원을 1명 이상 선택해주세요.")
                            else:
                                c = conn.cursor()
                                deleted_names = []
                                for emp_n, emp_b in selected_emp_to_delete:
                                    if emp_b: c.execute("DELETE FROM personal_records WHERE emp_name = ? AND birthdate = ?", (emp_n, emp_b))
                                    else: c.execute("DELETE FROM personal_records WHERE emp_name = ?", (emp_n,))
                                    deleted_names.append(emp_n)
                                conn.commit()
                                st.warning(f"선택하신 {len(deleted_names)}명({', '.join(deleted_names)})의 봉사 실적이 삭제되었습니다.")
                                st.rerun()

                    with del_tab2:
                        selected_records_to_delete = []
                        for _, r in dash_df.iterrows():
                            c_chk_rec, c_desc_rec = st.columns([0.8, 6.2])
                            with c_chk_rec:
                                if st.checkbox("선택", key=f"chk_del_rec_{r['id']}"):
                                    selected_records_to_delete.append(r['id'])
                            with c_desc_rec:
                                st.write(f"📅 **{r['활동기간']}** | **{r['성명']}** ({r['소속부서']}) — **[{r['분야']}] {r['봉사내용']}** (`{r['봉사시간']}시간`)")
                                st.caption(f"관할/기관: {r['관할센터_실적등록기관']} | 등록일시: {r['등록일시']}")
                        
                        if st.button(f"🗑️ 선택한 실적 항목(총 {len(selected_records_to_delete)}건) 일괄 삭제", type="primary", key="btn_bulk_del_rec_submit"):
                            if not selected_records_to_delete:
                                st.warning("삭제할 실적 항목을 1개 이상 선택해주세요.")
                            else:
                                c = conn.cursor()
                                c.executemany("DELETE FROM personal_records WHERE id = ?", [(rid,) for rid in selected_records_to_delete])
                                conn.commit()
                                st.warning(f"선택하신 {len(selected_records_to_delete)}건의 실적이 삭제되었습니다.")
                                st.rerun()

            with tab_stat2:
                st.subheader("👤 임직원 개개인별 종합 봉사활동 이력 명세")
                st.caption("👇 **상단 드롭다운에서 직원을 선택하거나, 아래 표에서 직원을 선택하시면 하단에 해당 직원의 1365 확인서 상세 실적이 즉시 출력됩니다.**")
                
                all_records_df = pd.read_sql_query("""
                    SELECT id, emp_name AS 성명, dept AS 소속부서, birthdate AS 생년월일,
                           v_date AS 활동기간, v_hours AS 봉사시간, v_category AS 분야,
                           v_title AS 봉사내용, v_org AS 관할센터_실적등록기관, uploaded_at AS 등록일시
                FROM personal_records
                ORDER BY v_date DESC
            """, conn)

                if all_records_df.empty:
                    st.info("등록된 자원봉사 실적 데이터가 없습니다.")
                else:
                    emp_grouped = all_records_df.groupby(['성명', '소속부서', '생년월일']).agg(
                        총봉사시간=('봉사시간', 'sum'),
                        활동건수=('봉사시간', 'count'),
                        최초활동일=('활동기간', 'min'),
                        최근활동일=('활동기간', 'max'),
                        주요분야=('분야', lambda x: x.value_counts().index[0] if len(x) > 0 else ""),
                        관할기관목록=('관할센터_실적등록기관', lambda x: ", ".join(sorted(set(str(v) for v in x if v))))
                    ).reset_index()
                    
                    emp_grouped['총봉사시간'] = emp_grouped['총봉사시간'].round(1)
                    emp_grouped['활동기간'] = emp_grouped['최초활동일'] + " ~ " + emp_grouped['최근활동일']
                    emp_grouped = sort_by_dept(emp_grouped)
                    
                    cols_to_show = [c for c in ['순번', '성명', '소속부서', '생년월일', '활동기간', '총봉사시간', '활동건수', '주요분야', '관할기관목록'] if c in emp_grouped.columns]
                    display_summary_table = emp_grouped[cols_to_show]

                    # 1. 드롭다운 선택 메뉴 추가 (직관적 제어)
                    all_emp_names = sorted(display_summary_table['성명'].unique())
                    
                    if "selected_emp_dropdown" not in st.session_state:
                        st.session_state["selected_emp_dropdown"] = all_emp_names[0] if all_emp_names else ""

                    c_sel1, c_sel2 = st.columns([2, 3])
                    with c_sel1:
                        selected_emp_name = st.selectbox("🔍 조회할 직원 선택", all_emp_names, key="selected_emp_dropdown")
                    with c_sel2:
                        st.write("")
                        st.caption(f"💡 현재 선택된 직원: **{selected_emp_name}** (드롭다운을 바꾸거나 표에서 행을 클릭하세요)")

                    event = st.dataframe(
                        display_summary_table,
                        use_container_width=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key="emp_table_selector_v3"
                    )

                    # 표 행을 클릭한 경우 드롭다운 선택값도 함께 연동
                    sel_rows = event.selection.get("rows", [])
                    if sel_rows:
                        clicked_emp = display_summary_table.iloc[sel_rows[0]]['성명']
                        if clicked_emp != st.session_state["selected_emp_dropdown"]:
                            st.session_state["selected_emp_dropdown"] = clicked_emp
                            st.rerun()

                    st.divider()
                    
                    target_emp_name = st.session_state["selected_emp_dropdown"]
                    target_emp_df = all_records_df[all_records_df['성명'] == target_emp_name].copy()
                    
                    t_dept = target_emp_df.iloc[0]['소속부서'] if not target_emp_df.empty else "소속없음"
                    t_birth = target_emp_df.iloc[0]['생년월일'] if not target_emp_df.empty else ""
                    t_total_hrs = target_emp_df['봉사시간'].sum() if not target_emp_df.empty else 0.0
                    t_min_date = target_emp_df['활동기간'].min() if not target_emp_df.empty else ""
                    t_max_date = target_emp_df['활동기간'].max() if not target_emp_df.empty else ""
                    
                    with st.container(border=True):
                        st.markdown(f"### 🏅 **{target_emp_name}** 직원 상세 활동실적 명세서")
                        c_t1, c_t2, c_t3 = st.columns(3)
                        with c_t1: st.write(f"🏢 **소속:** {t_dept} | 🎂 **생년월일:** {t_birth or '미기재'}")
                        with c_t2: st.write(f"📅 **활동기간:** {t_min_date} ~ {t_max_date}")
                        with c_t3: st.write(f"⏱️ **누적 봉사시간:** `{round(t_total_hrs, 1)}시간` (총 {len(target_emp_df)}건)")
                        
                        st.write("")
                        st.write("##### ■ 자원봉사 활동실적 (1365 확인서 2페이지 상세 내역)")
                        if not target_emp_df.empty:
                            view_target_df = target_emp_df[['활동기간', '봉사시간', '분야', '봉사내용', '관할센터 / 실적등록기관' if '관할센터 / 실적등록기관' in target_emp_df.columns else '관할센터_실적등록기관']]
                            view_target_df.columns = ['활동기간(일자)', '봉사시간(h)', '분야', '봉사내용', '관할센터 / 실적등록기관']
                            view_target_df.insert(0, '순번', range(1, len(view_target_df) + 1))
                            st.dataframe(view_target_df, use_container_width=True)
                        else:
                            st.info("등록된 실적이 없습니다.")

        # =========================================================
        # 2구역: 사내 단체 봉사활동 운영 관리
        # =========================================================
        elif admin_section == "🗓️ [사내 단체 봉사활동 운영]":
            tab_act1, tab_act2, tab_act3 = st.tabs([
                "➕ 일감 등록 & 모집/마감 관리",
                "✅ 출석 체크 & 현장 명단 엑셀",
                "📋 단체 봉사 추진 결과보고서"
            ])

            with tab_act1:
                st.subheader("➕ 신규 봉사 일감 등록")
                with st.form("add_act_form", clear_on_submit=True):
                    title = st.text_input("봉사활동명 *")
                    c_d1, c_d2 = st.columns(2)
                    with c_d1: date = st.text_input("봉사 활동 일시 *", placeholder="2026-09-12 14:00~17:00")
                    with c_d2: deadline = st.text_input("모집 마감 일시", placeholder="2026-09-10 18:00")
                    c_cat, c_h, c_c = st.columns(3)
                    with c_cat: category = st.selectbox("활동 분야", ["환경정화 / 생태보전", "안전예방 / 재난구호", "사회복지 / 소외계층지원", "문화·체육 / 행사지원", "교육·멘토링 / 청소년", "기타 / 공익봉사"])
                    with c_h: hours = st.number_input("인정 시간", min_value=0.5, step=0.5, value=2.0)
                    with c_c: capacity = st.number_input("정원 (명)", min_value=1, step=1, value=10)
                    location = st.text_input("집결/활동 장소 *")
                    description = st.text_area("상세 안내")
                    if st.form_submit_button("새 일감 등록하기", use_container_width=True):
                        if title.strip() and date.strip() and location.strip():
                            c = conn.cursor()
                            c.execute("INSERT INTO activities (title, date, deadline, location, category, hours, max_capacity, description, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '모집중')", (title.strip(), date.strip(), deadline.strip(), location.strip(), category, hours, capacity, description.strip()))
                            conn.commit()
                            st.success("등록 완료")
                            st.rerun()

                st.divider()
                st.subheader("📋 등록된 봉사활동 일감 상태 관리")
                all_acts = pd.read_sql_query("SELECT * FROM activities ORDER BY id DESC", conn)
                if not all_acts.empty:
                    for _, act in all_acts.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 1.5, 1])
                            with c1: st.write(f"**[{act['status']}] {act['title']}** | {act['date']} | 분야: `{act.get('category', '환경')}`")
                            with c2:
                                new_st = st.selectbox("상태", ["모집중", "모집마감", "활동종료"], index=["모집중", "모집마감", "활동종료"].index(act['status']) if act['status'] in ["모집중", "모집마감", "활동종료"] else 0, key=f"sel_st_{act['id']}")
                                if st.button("저장", key=f"btn_st_{act['id']}"):
                                    c = conn.cursor()
                                    c.execute("UPDATE activities SET status = ? WHERE id = ?", (new_st, act['id']))
                                    conn.commit()
                                    st.rerun()
                            with c3:
                                if st.button("삭제", key=f"del_act_{act['id']}", type="primary"):
                                    c = conn.cursor()
                                    c.execute("DELETE FROM applications WHERE activity_id = ?", (act['id'],))
                                    c.execute("DELETE FROM activities WHERE id = ?", (act['id'],))
                                    conn.commit()
                                    st.rerun()

            with tab_act2:
                st.subheader("👥 개별 활동 출석 관리 & 서명부 엑셀")
                acts = pd.read_sql_query("SELECT id, title, date, hours, max_capacity, status FROM activities ORDER BY id DESC", conn)
                if not acts.empty:
                    act_select_map = {f"[{row['status']}] [{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                    target_act_name = st.selectbox("활동 선택", list(act_select_map.keys()), key="admin_att_act_v2")
                    target_act_id = act_select_map[target_act_name]
                    current_act = acts[acts['id'] == target_act_id].iloc[0]
                    max_cap = current_act['max_capacity']
                    app_df = pd.read_sql_query("SELECT id, name, dept, birthdate, phone, v1365_id, applied_at, attendance FROM applications WHERE activity_id = ? ORDER BY id ASC", conn, params=(target_act_id,))

                    col_ex1, col_ex2 = st.columns(2)
                    with col_ex1:
                        if not app_df.empty:
                            excel_all_df = app_df.copy()
                            excel_all_df.insert(0, '구분', ["정원내" if i < max_cap else f"대기{i - max_cap + 1}" for i in range(len(excel_all_df))])
                            excel_all_df.insert(1, '순번', range(1, len(excel_all_df) + 1))
                            excel_all_df['서명'] = ""; excel_all_df['비고'] = ""
                            excel_all_df = excel_all_df[['순번', '구분', 'name', 'dept', 'birthdate', 'phone', 'v1365_id', 'applied_at', '서명', '비고']]
                            excel_all_df.columns = ['순번', '구분', '성명', '소속부서', '생년월일', '휴대폰번호', '1365 자원봉사 ID', '신청일시', '서명', '비고']
                            all_excel_bytes = create_styled_excel(excel_all_df, f"{current_act['title']} 명단", current_act['date'], hours_val=current_act['hours'], sheet_name='명단', is_attendance=True)
                            st.download_button("📥 명단 엑셀 다운로드 (서명란 포함)", data=all_excel_bytes, file_name=f"{current_act['title']}_명단_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                    with col_ex2:
                        if not app_df.empty:
                            attended_df = app_df[app_df['attendance'] == '참석'].copy()
                            if not attended_df.empty:
                                attended_df.insert(0, '순번', range(1, len(attended_df) + 1))
                                attended_df = attended_df[['순번', 'name', 'dept', 'birthdate', 'phone', 'v1365_id', 'attendance']]
                                attended_df.columns = ['순번', '성명', '소속부서', '생년월일', '휴대폰번호', '1365 자원봉사 ID', '참석여부']
                                att_excel_bytes = create_styled_excel(attended_df, f"{current_act['title']} 참석자 명단", current_act['date'], hours_val=current_act['hours'], sheet_name='참석자명단', is_attendance=False)
                                st.download_button("⭐ [1365 제출용] 참석자 명단 엑셀 다운로드", data=att_excel_bytes, file_name=f"{current_act['title']}_참석자명단_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

                    st.divider()
                    if not app_df.empty:
                        updated_attendance = {}
                        for idx, row in app_df.iterrows():
                            is_wait = idx >= max_cap
                            tag = f"🔴 [대기 {idx - max_cap + 1}번]" if is_wait else "🟢 [정원내]"
                            with st.container(border=True):
                                c_info, c_att = st.columns([3, 2])
                                with c_info: st.write(f"**{idx+1}. {row['name']}** {tag} ({row['dept']} / {row['birthdate']})")
                                with c_att:
                                    current_att = row['attendance'] if row['attendance'] in ['대기', '참석', '불참'] else '대기'
                                    choice = st.radio("출석", ["대기", "참석", "불참"], index=["대기", "참석", "불참"].index(current_att), key=f"att_radio_{row['id']}", horizontal=True)
                                    updated_attendance[row['id']] = choice
                        if st.button("💾 출석 체크 일괄 저장", type="primary", use_container_width=True):
                            c = conn.cursor()
                            for app_id, att_val in updated_attendance.items():
                                c.execute("UPDATE applications SET attendance = ? WHERE id = ?", (att_val, app_id))
                            conn.commit()
                            st.success("저장 완료")
                            st.rerun()

            with tab_act3:
                st.subheader("📊 단체 봉사활동 결과보고서")
                all_act_list = pd.read_sql_query("SELECT * FROM activities ORDER BY date ASC", conn)
                if not all_act_list.empty:
                    summary_rows = []
                    for idx, act in all_act_list.iterrows():
                        c = conn.cursor()
                        c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ?", (act['id'],))
                        applied_cnt = c.fetchone()[0]
                        c.execute("SELECT COUNT(*) FROM applications WHERE activity_id = ? AND attendance = '참석'", (act['id'],))
                        attended_cnt = c.fetchone()[0]
                        summary_rows.append({
                            "연번": idx + 1, "봉사활동명": act['title'], "분야": act.get('category', '환경'), "활동일시": act['date'], "장소": act['location'],
                            "인정시간(h)": act['hours'], "정원": act['max_capacity'], "신청인원": applied_cnt, "참석인원": attended_cnt,
                            "총 누적시간(h)": round(attended_cnt * act['hours'], 1), "상태": act['status']
                        })
                    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

        # =========================================================
        # 3구역: 시스템 설정 & 대리등록
        # =========================================================
        elif admin_section == "⚙️ [시스템 관리]":
            tab_sys1, tab_sys2 = st.tabs(["✍️ 사전 신청자 대리등록", "🔐 관리자 비밀번호 변경"])
            
            with tab_sys1:
                st.subheader("✍️ 사전 신청자 대리등록")
                acts = pd.read_sql_query("SELECT id, title, date FROM activities ORDER BY id DESC", conn)
                if not acts.empty:
                    act_map = {f"[{row['date']}] {row['title']}": row['id'] for _, row in acts.iterrows()}
                    with st.form("admin_manual_apply_form", clear_on_submit=True):
                        sel_act = st.selectbox("활동 선택", list(act_map.keys()))
                        m_name = st.text_input("1. 성명 *")
                        m_dept = st.selectbox("2. 부서 *", DEPT_ORDER)
                        m_birth = st.text_input("3. 생년월일 *")
                        m_phone = st.text_input("4. 휴대폰 *")
                        m_1365 = st.text_input("5. 1365 ID")
                        if st.form_submit_button("등록 완료", use_container_width=True):
                            if m_name.strip() and m_birth.strip() and m_phone.strip():
                                c = conn.cursor()
                                c.execute("INSERT INTO applications (activity_id, name, dept, birthdate, phone, v1365_id, applied_at, attendance) VALUES (?, ?, ?, ?, ?, ?, ?, '대기')", (act_map[sel_act], m_name.strip(), m_dept.strip(), format_birthdate(m_birth), m_phone.strip(), m_1365.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S (관리자등록)")))
                                conn.commit()
                                st.success("등록되었습니다.")
                                st.rerun()

            with tab_sys2:
                st.subheader("🔐 관리자 비밀번호 변경")
                with st.form("change_pw_form", clear_on_submit=True):
                    old_pw = st.text_input("현재 비밀번호 *", type="password")
                    new_pw1 = st.text_input("새 비밀번호 *", type="password")
                    new_pw2 = st.text_input("새 비밀번호 확인 *", type="password")
                    if st.form_submit_button("변경하기", type="primary"):
                        if old_pw != current_saved_pw: st.error("현재 비밀번호 불일치")
                        elif not new_pw1.strip(): st.warning("비밀번호 입력 필요")
                        elif new_pw1 != new_pw2: st.error("확인 불일치")
                        else:
                            update_admin_password(new_pw1.strip())
                            st.session_state["pw_changed_notice"] = True
                            st.rerun()

        conn.close()
