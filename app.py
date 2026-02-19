import streamlit as st
import json
import os
import glob
import pdfplumber
import pandas as pd
import shutil
from datetime import datetime
import base64

# ==========================================
# ⚙️ 설정 및 경로
# ==========================================
st.set_page_config(layout="wide", page_title="CPA 데이터셋 수정 도구")

# 데이터 파일 경로 (사용자 환경에 맞게 수정 가능)
DATA_FILE = "cpa_2016_2025_combined.jsonl"
PDF_ARCHIVE_DIR = os.path.join("data", "raw_pdfs")
BACKUP_DIR = "backups"
ERROR_REPORT_FILE = os.path.join("data", "error_report.md")
UPLOAD_DIR = os.path.join("data", "uploads")
MANUAL_CHECK_FILE = os.path.join("data", "manual_check_status.json")
REVIEW_STATUS_FILE = os.path.join("data", "review_status.json")

# 필요한 디렉토리 생성
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==========================================
# 📋 오류 리포트 파싱
# ==========================================
# ==========================================
# 📋 수동 체크 상태 관리
# ==========================================
def load_manual_check_status():
    """수동 체크 상태 로드"""
    if not os.path.exists(MANUAL_CHECK_FILE):
        return {}
    
    try:
        with open(MANUAL_CHECK_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('checked_questions', {})
    except Exception as e:
        st.warning(f"수동 체크 상태 로드 실패: {e}")
        return {}

def save_manual_check_status(checked_questions):
    """수동 체크 상태 저장"""
    try:
        data = {
            "description": "수동으로 확인한 문항의 체크 상태를 저장합니다.",
            "format": "year_subject_questionNumber: true/false",
            "checked_questions": checked_questions
        }
        with open(MANUAL_CHECK_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"수동 체크 상태 저장 실패: {e}")
        return False

def get_check_key(year, subject, question_number):
    """체크 상태 키 생성"""
    return f"{year}_{subject}_{question_number}"

def is_manually_checked(year, subject, question_number, check_status):
    """해당 문항이 수동으로 체크되었는지 확인"""
    key = get_check_key(year, subject, question_number)
    return check_status.get(key, False)

# ==========================================
# ✅ 문항 검토 상태 관리
# ==========================================
def load_review_status():
    """문항 검토 상태 로드"""
    if not os.path.exists(REVIEW_STATUS_FILE):
        return {}
    try:
        with open(REVIEW_STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('reviewed_questions', {})
    except Exception:
        return {}

def save_review_status(reviewed):
    """문항 검토 상태 저장"""
    try:
        data = {
            "description": "문항별 검토 완료 상태를 저장합니다.",
            "format": "unique_id: {checked: bool, timestamp: str}",
            "reviewed_questions": reviewed
        }
        with open(REVIEW_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def get_review_stats(all_data, reviewed, year=None, subject=None):
    """검토 진행 통계 반환"""
    targets = all_data
    if year:
        targets = [d for d in targets if d.get('metadata', {}).get('year') == year]
    if subject:
        targets = [d for d in targets if d.get('metadata', {}).get('subject') == subject]
    total = len(targets)
    done = sum(1 for d in targets if reviewed.get(d.get('unique_id', ''), {}).get('checked', False))
    return total, done

@st.cache_data
def load_error_report():
    """error_report.md 파일을 파싱하여 누락된 문항 정보 반환"""
    missing_questions = {}  # {year: {subject: [question_numbers]}}
    
    if not os.path.exists(ERROR_REPORT_FILE):
        return missing_questions
    
    try:
        with open(ERROR_REPORT_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_year = None
        current_subject = None
        
        for line in lines:
            line = line.strip()
            
            # 연도 파싱 (예: [ ✅ 2016년 ])
            if line.startswith('[') and '년' in line:
                try:
                    year_str = line.split('[')[1].split(']')[0].strip()
                    # "✅ 2016년" -> "2016"
                    current_year = ''.join(filter(str.isdigit, year_str))
                    if current_year:
                        missing_questions[current_year] = {}
                except:
                    continue
            
            # 과목 파싱 (예: 📌 경제원론)
            elif line.startswith('📌') and current_year:
                try:
                    current_subject = line.split('📌')[1].strip()
                    if current_subject and current_year:
                        missing_questions[current_year][current_subject] = []
                except:
                    continue
            
            # 문항 번호 파싱 (예: - 21~38번 문항이 아예 추출되지 않음)
            elif line.startswith('-') and current_year and current_subject:
                try:
                    # 숫자 범위 추출
                    import re
                    # "21~38번" 또는 "21번" 패턴 찾기
                    patterns = re.findall(r'(\d+)~(\d+)번|(\d+)번', line)
                    
                    for pattern in patterns:
                        if pattern[0] and pattern[1]:  # 범위 (21~38)
                            start = int(pattern[0])
                            end = int(pattern[1])
                            for num in range(start, end + 1):
                                if num not in missing_questions[current_year][current_subject]:
                                    missing_questions[current_year][current_subject].append(num)
                        elif pattern[2]:  # 단일 번호 (21번)
                            num = int(pattern[2])
                            if num not in missing_questions[current_year][current_subject]:
                                missing_questions[current_year][current_subject].append(num)
                except:
                    continue
        
        # 각 과목의 문항 번호를 정렬
        for year in missing_questions:
            for subject in missing_questions[year]:
                missing_questions[year][subject].sort()
        
    except Exception as e:
        st.warning(f"오류 리포트 파싱 중 오류: {e}")
    
    return missing_questions

# ==========================================
# 💾 데이터 로드/저장 함수
# ==========================================
def validate_entry(entry):
    """데이터 항목의 필수 필드를 검증"""
    required_fields = ['conversation', 'metadata', 'unique_id']
    required_metadata = ['year', 'subject', 'question_number', 'source']
    
    # 필수 필드 체크
    for field in required_fields:
        if field not in entry:
            return False, f"필수 필드 '{field}'가 누락되었습니다."
    
    # conversation 구조 체크
    if not isinstance(entry['conversation'], list) or len(entry['conversation']) < 2:
        return False, "conversation은 최소 2개의 메시지를 포함해야 합니다."
    
    # metadata 필수 필드 체크
    for field in required_metadata:
        if field not in entry['metadata']:
            return False, f"metadata에 필수 필드 '{field}'가 누락되었습니다."
    
    # unique_id 형식 체크
    if not isinstance(entry['unique_id'], str) or not entry['unique_id'].strip():
        return False, "unique_id는 비어있지 않은 문자열이어야 합니다."
    
    return True, "검증 성공"

@st.cache_data
def load_data():
    """JSONL 파일을 로드하여 리스트로 반환"""
    data = []
    if not os.path.exists(DATA_FILE):
        st.warning(f"데이터 파일 '{DATA_FILE}'을 찾을 수 없습니다. 새로운 파일이 생성됩니다.")
        return data
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            line_num = 0
            for line in f:
                line_num += 1
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    entry = json.loads(line)
                    is_valid, msg = validate_entry(entry)
                    if is_valid:
                        data.append(entry)
                    else:
                        st.warning(f"라인 {line_num}: 유효하지 않은 데이터 - {msg}")
                except json.JSONDecodeError as je:
                    st.warning(f"라인 {line_num}: JSON 파싱 오류 - {je}")
                    
    except PermissionError:
        st.error(f"파일 '{DATA_FILE}' 읽기 권한이 없습니다.")
    except Exception as e:
        st.error(f"데이터 파일 로드 중 예기치 않은 오류 발생: {e}")
    
    return data

def create_backup():
    """현재 데이터 파일의 백업 생성"""
    if not os.path.exists(DATA_FILE):
        return True, "백업할 파일이 없습니다."
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(BACKUP_DIR, f"backup_{timestamp}.jsonl")
        shutil.copy2(DATA_FILE, backup_file)
        return True, backup_file
    except Exception as e:
        return False, f"백업 생성 실패: {e}"

def save_data_to_file(data_list):
    """메모리 상의 데이터를 JSONL 파일로 덮어쓰기 (정렬 후 저장)"""
    if not data_list:
        st.warning("저장할 데이터가 없습니다.")
        return False
    
    # 백업 생성
    backup_success, backup_msg = create_backup()
    if not backup_success:
        st.error(f"백업 실패: {backup_msg}")
        return False
    
    # 데이터 정렬 (연도 → 과목 → 문항번호 순)
    def sort_key(entry):
        try:
            year = entry.get('metadata', {}).get('year', '9999')
            subject = entry.get('metadata', {}).get('subject', 'ZZZ')
            question_number = entry.get('metadata', {}).get('question_number', 99999)
            # 문항 번호를 정수로 변환 (실패 시 99999)
            try:
                question_number = int(question_number)
            except (ValueError, TypeError):
                question_number = 99999
            return (year, subject, question_number)
        except Exception:
            return ('9999', 'ZZZ', 99999)
    
    sorted_data_list = sorted(data_list, key=sort_key)
    
    # 임시 파일에 먼저 쓰기
    temp_file = DATA_FILE + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            for entry in sorted_data_list:
                # 저장 전 재검증
                is_valid, msg = validate_entry(entry)
                if not is_valid:
                    st.error(f"저장 실패: {msg}")
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    return False
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        # 임시 파일을 실제 파일로 이동
        shutil.move(temp_file, DATA_FILE)
        return True
        
    except PermissionError:
        st.error(f"파일 '{DATA_FILE}' 쓰기 권한이 없습니다.")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False
    except Exception as e:
        st.error(f"저장 중 오류 발생: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False

# ==========================================
# 📄 PDF 처리 함수
# ==========================================
def display_pdf(pdf_path):
    """PDF 파일을 브라우저에서 볼 수 있도록 base64로 인코딩"""
    try:
        with open(pdf_path, "rb") as f:
            base64_pdf = base64.b64encode(f.read()).decode('utf-8')
        
        # PDF를 iframe으로 표시 (navpanes=0 → 왼쪽 썸네일 패널 숨김)
        pdf_display = f'''
        <iframe src="data:application/pdf;base64,{base64_pdf}#navpanes=0&scrollbar=1&view=FitH" 
                width="100%" 
                height="800px" 
                type="application/pdf"
                style="border: 1px solid #ddd;">
        </iframe>
        '''
        return pdf_display, True
    except Exception as e:
        return f"PDF 표시 실패: {e}", False

@st.cache_data
def extract_text_from_pdf(pdf_path):
    """PDF에서 텍스트 추출 (캐싱 사용)"""
    if not pdf_path or not os.path.exists(pdf_path):
        return f"PDF 파일이 존재하지 않습니다: {pdf_path}"
    
    if not os.access(pdf_path, os.R_OK):
        return f"PDF 파일 읽기 권한이 없습니다: {pdf_path}"
    
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return "PDF 파일에 페이지가 없습니다."
            
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n\n"
                except Exception as page_error:
                    st.warning(f"페이지 {page_num} 추출 중 오류: {page_error}")
                    
    except FileNotFoundError:
        return f"PDF 파일을 찾을 수 없습니다: {pdf_path}"
    except PermissionError:
        return f"PDF 파일 접근 권한이 없습니다: {pdf_path}"
    except Exception as e:
        return f"PDF 읽기 실패: {type(e).__name__} - {e}"
    
    if not full_text.strip():
        return "PDF에서 텍스트를 추출할 수 없습니다. (스캔된 이미지일 수 있습니다)"
    
    return full_text

def find_pdf_path(year, subject):
    """연도와 과목명으로 PDF 파일 경로 찾기"""
    # 입력 유효성 검증
    if not year or not subject:
        return None, "연도 또는 과목 정보가 없습니다."
    
    if not os.path.exists(PDF_ARCHIVE_DIR):
        return None, f"PDF 디렉토리를 찾을 수 없습니다: {PDF_ARCHIVE_DIR}\n\n사이드바에서 PDF 경로를 설정하거나 PDF를 직접 업로드하세요."
    
    # 1. 연도 폴더 찾기
    # 패턴: "16년 공인회계사...", "2016년 공인회계사..." 모두 지원
    year_short = year[-2:] if len(year) == 4 else year  # "2016" -> "16"
    
    # 여러 패턴 시도
    year_patterns = [
        f"{year_short}년*",  # "16년 공인회계사..."
        f"{year}년*",         # "2016년 공인회계사..."
    ]
    
    year_folders = []
    for pattern in year_patterns:
        year_glob = os.path.join(PDF_ARCHIVE_DIR, pattern)
        found = glob.glob(year_glob)
        year_folders.extend(found)
    
    if not year_folders:
        return None, f"'{year}'년도 폴더를 찾을 수 없습니다.\n검색 경로: {PDF_ARCHIVE_DIR}\n\n사이드바에서 PDF를 직접 업로드하거나 경로를 확인하세요."
    
    target_folder = year_folders[0]  # 첫 번째 매칭되는 폴더 사용
    
    if not os.path.isdir(target_folder):
        return None, f"'{target_folder}'가 디렉토리가 아닙니다."
    
    # 2. 과목명 매칭 (파일명에 과목명이 포함된 것 찾기)
    # 과목명 정규화 (여러 변형 지원)
    subject_keywords = [subject]
    
    # 과목명의 앞 2-3글자로도 검색
    if len(subject) >= 3:
        subject_keywords.append(subject[:3])
    if len(subject) >= 2:
        subject_keywords.append(subject[:2])
    
    # 특수 케이스 처리
    subject_map = {
        '경제원론': ['경제원론', '경제학', '경제'],
        '경제학': ['경제학', '경제원론', '경제'],
        '상법': ['상법', '세법', '상법 세법'],  # 상법/세법 합본일 수도
        '세법': ['세법', '상법', '세법개론'],
        '세법개론': ['세법개론', '세법'],
        '경영학': ['경영학', '경영'],
        '회계학': ['회계학', '회계'],
    }
    
    if subject in subject_map:
        subject_keywords = subject_map[subject]
    
    # PDF 파일 검색
    pdf_files = []
    for keyword in subject_keywords:
        found = glob.glob(os.path.join(target_folder, f"*{keyword}*.pdf"))
        # 정답 파일 제외
        found = [f for f in found if '정답' not in os.path.basename(f) and '가답안' not in os.path.basename(f)]
        pdf_files.extend(found)
    
    # 중복 제거
    pdf_files = list(set(pdf_files))
    
    if not pdf_files:
        available_files = glob.glob(os.path.join(target_folder, "*.pdf"))
        file_list = "\n  - ".join([os.path.basename(f) for f in available_files[:5]])
        return None, f"'{target_folder}' 내에서 '{subject}' 관련 PDF를 찾을 수 없습니다.\n\n사용 가능한 파일 (일부):\n  - {file_list}\n\n사이드바에서 PDF를 직접 업로드하세요."
    
    # 가장 관련성 높은 파일 선택
    def score_filename(filepath):
        basename = os.path.basename(filepath)
        score = 0
        if subject in basename:
            score += 10
        for keyword in subject_keywords:
            if keyword in basename:
                score += 5
        return score
    
    best_match = max(pdf_files, key=score_filename)
    
    return best_match, "Success"

def find_answer_pdf_path(year):
    """연도별 정답 PDF 파일 경로 찾기"""
    if not year:
        return None, "연도 정보가 없습니다."
    
    if not os.path.exists(PDF_ARCHIVE_DIR):
        return None, f"PDF 디렉토리를 찾을 수 없습니다: {PDF_ARCHIVE_DIR}"
    
    # 1. 연도 폴더 찾기
    year_short = year[-2:] if len(year) == 4 else year  # "2016" -> "16"
    
    year_patterns = [
        f"{year_short}년*",
        f"{year}년*",
    ]
    
    year_folders = []
    for pattern in year_patterns:
        year_glob = os.path.join(PDF_ARCHIVE_DIR, pattern)
        found = glob.glob(year_glob)
        year_folders.extend(found)
    
    if not year_folders:
        return None, f"'{year}'년도 폴더를 찾을 수 없습니다."
    
    target_folder = year_folders[0]
    
    if not os.path.isdir(target_folder):
        return None, f"'{target_folder}'가 디렉토리가 아닙니다."
    
    # 2. 정답 파일 검색 (여러 패턴 지원)
    answer_keywords = ['정답', '답안', '가답안']
    answer_files = []
    
    for keyword in answer_keywords:
        found = glob.glob(os.path.join(target_folder, f"*{keyword}*.pdf"))
        answer_files.extend(found)
    
    # 중복 제거
    answer_files = list(set(answer_files))
    
    if not answer_files:
        return None, f"'{target_folder}' 내에서 정답 PDF를 찾을 수 없습니다."
    
    # 우선순위: "확정정답" > "전체정답" > "최종정답" > "정답" > "답안" > "가답안"
    priority_keywords = ['확정정답', '전체정답', '최종정답', '정답', '답안', '가답안']
    
    def score_answer_filename(filepath):
        basename = os.path.basename(filepath)
        for idx, keyword in enumerate(priority_keywords):
            if keyword in basename:
                return len(priority_keywords) - idx
        return 0
    
    best_match = max(answer_files, key=score_answer_filename)
    
    return best_match, "Success"

def extract_answer_from_content(content):
    """assistant content에서 정답만 추출 (예: '정답: ③' -> '③', '정답: 3' -> '3')"""
    if not content or not isinstance(content, str):
        return ""
    import re
    s = content.strip()
    for prefix in ("정답:", "최종정답:"):
        if prefix in s:
            s = s.split(prefix)[-1].strip().split("\n")[0].strip()
            break
    m = re.search(r"[①②③④⑤]", s)
    if m:
        return m.group(0)
    m = re.search(r"\b([1-5])\b", s)
    if m:
        return m.group(1)
    return s[:20] if s else ""


def parse_answer_key_text(text):
    """
    정답표 텍스트 파싱. 한 줄에 '문항번호 정답' 형태.
    예: '1 ①', '2. ②', '3:③', '4 4', '1 1' -> {1: '①', 2: '②', 3: '③', 4: '④'}
    """
    import re
    result = {}
    choice_map = {"1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤"}
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # 문항번호: 줄 맨 앞 숫자
        num_m = re.match(r"^\s*(\d+)\s*", line)
        if not num_m:
            continue
        q_num = int(num_m.group(1))
        rest = line[num_m.end():].strip()
        # 정답: ①②③④⑤ 우선, 없으면 1~5
        ans_m = re.search(r"[①②③④⑤]", rest) or re.search(r"\b([1-5])\b", rest)
        if ans_m:
            raw = ans_m.group(0)
            result[q_num] = choice_map.get(raw, raw)
    return result


def normalize_answer_for_compare(a):
    """비교용 정규화: ①~⑤ 및 1~5를 1~5로 통일"""
    if not a:
        return ""
    if a in ("①", "1"):
        return "1"
    if a in ("②", "2"):
        return "2"
    if a in ("③", "3"):
        return "3"
    if a in ("④", "4"):
        return "4"
    if a in ("⑤", "5"):
        return "5"
    return str(a).strip()


def parse_jsonl_answer_key(text):
    """
    붙여넣은 텍스트가 JSON/JSONL 형태면 파싱.
    반환: (entries: list of dict, error: str or None)
    각 entry는 unique_id, metadata.question_number, conversation 등 포함.
    """
    if not text or not text.strip():
        return [], None
    raw = text.strip()
    entries = []
    # 한 줄 한 줄 JSON (JSONL)
    if raw.startswith("{"):
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict) and ("conversation" in entry or "metadata" in entry):
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
        if entries:
            return entries, None
    # 단일 JSON 배열
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and ("conversation" in item or "metadata" in item):
                        entries.append(item)
                return entries, None
        except json.JSONDecodeError as e:
            return [], str(e)
    return [], None


def match_subject(selected_subject, error_report_subject):
    """과목명 매칭 함수 - 더 정확한 매칭"""
    # 정확히 일치하는 경우
    if selected_subject == error_report_subject:
        return True
    
    # 슬래시로 구분된 복합 과목 처리 (예: "상법 / 세법개론")
    if ' / ' in error_report_subject:
        parts = [p.strip() for p in error_report_subject.split('/')]
        if selected_subject in parts:
            return True
    
    # 과목명이 오류 리포트에 포함되어 있는 경우 (예: "경제원론" vs "경제학")
    # 하지만 너무 짧은 문자열은 제외 (예: "법"은 "상법", "세법", "기업법" 모두 매칭됨)
    if len(selected_subject) >= 3:
        if selected_subject in error_report_subject:
            return True
    
    # 경제학과 경제원론은 같은 것으로 취급
    if (selected_subject in ['경제학', '경제원론'] and 
        error_report_subject in ['경제학', '경제원론']):
        return True
    
    return False

# ==========================================
# 🔄 세션 상태 초기화
# ==========================================
if 'data' not in st.session_state:
    st.session_state['data'] = load_data()

if 'manual_check_status' not in st.session_state:
    st.session_state['manual_check_status'] = load_manual_check_status()

if 'review_status' not in st.session_state:
    st.session_state['review_status'] = load_review_status()

# 전체 데이터 참조
all_data = st.session_state['data']
manual_check_status = st.session_state['manual_check_status']
review_status = st.session_state['review_status']

# ==========================================
# 🎛️ 사이드바: 필터링 및 통계
# ==========================================
st.sidebar.title("🔍 데이터 탐색기")

# PDF 설정
with st.sidebar.expander("⚙️ PDF 설정"):
    # PDF 경로 표시 및 수정
    st.text_input(
        "PDF 디렉토리",
        value=PDF_ARCHIVE_DIR,
        disabled=True,
        help="PDF 파일들이 저장된 디렉토리입니다."
    )
    
    # PDF 파일 직접 업로드
    st.markdown("#### 📤 PDF 직접 업로드")
    uploaded_pdf = st.file_uploader(
        "PDF 파일 선택",
        type=['pdf'],
        help="연도/과목의 PDF가 없을 경우 직접 업로드하세요.",
        key="pdf_upload"
    )
    
    if uploaded_pdf:
        # 업로드된 파일 저장
        upload_path = os.path.join(UPLOAD_DIR, uploaded_pdf.name)
        try:
            with open(upload_path, 'wb') as f:
                f.write(uploaded_pdf.getbuffer())
            st.success(f"✅ 업로드 완료: {uploaded_pdf.name}")
            st.info(f"저장 위치: {upload_path}")
            
            # 세션 상태에 업로드된 파일 경로 저장
            if 'uploaded_pdf_path' not in st.session_state:
                st.session_state['uploaded_pdf_path'] = {}
            st.session_state['uploaded_pdf_path']['latest'] = upload_path
            
        except Exception as e:
            st.error(f"업로드 실패: {e}")

st.sidebar.markdown("---")

# 데이터가 없는 경우 처리
if not all_data:
    st.sidebar.warning("로드된 데이터가 없습니다.")
    st.warning("데이터가 없습니다. 신규 문항을 추가하거나 데이터 파일을 확인하세요.")
    st.stop()

# 1. 연도 선택
try:
    years = sorted(list(set([
        d.get('metadata', {}).get('year', 'Unknown') 
        for d in all_data 
        if d and isinstance(d.get('metadata'), dict)
    ])))
    
    if not years or years == ['Unknown']:
        st.sidebar.error("유효한 연도 정보가 없습니다.")
        st.stop()
    
    # 기본 선택값 설정
    default_index = 0
    if "2016" in years:
        default_index = years.index("2016")
    
    selected_year = st.sidebar.selectbox("1. 연도 선택", years, index=default_index)
    
except Exception as e:
    st.sidebar.error(f"연도 데이터 처리 중 오류: {e}")
    st.stop()

# 2. 과목 선택
try:
    subjects_in_year = sorted(list(set([
        d.get('metadata', {}).get('subject', 'Unknown')
        for d in all_data
        if d 
        and isinstance(d.get('metadata'), dict)
        and d.get('metadata', {}).get('year') == selected_year
    ])))
    
    if not subjects_in_year or subjects_in_year == ['Unknown']:
        st.sidebar.warning(f"{selected_year}년도에 과목 데이터가 없습니다.")
        subjects_in_year = ['과목 없음']
    
    selected_subject = st.sidebar.selectbox("2. 과목 선택", subjects_in_year)
    
except Exception as e:
    st.sidebar.error(f"과목 데이터 처리 중 오류: {e}")
    st.stop()

# 3. 현재 데이터 필터링
try:
    filtered_indices = [
        i for i, d in enumerate(all_data)
        if d 
        and isinstance(d.get('metadata'), dict)
        and d.get('metadata', {}).get('year') == selected_year
        and d.get('metadata', {}).get('subject') == selected_subject
    ]
    
    # 문항 번호로 정렬 (안전한 정렬)
    def get_question_number(idx):
        try:
            return int(all_data[idx].get('metadata', {}).get('question_number', 0))
        except (ValueError, TypeError):
            return 0
    
    filtered_indices.sort(key=get_question_number)
    
except Exception as e:
    st.sidebar.error(f"데이터 필터링 중 오류: {e}")
    filtered_indices = []

st.sidebar.markdown("---")
st.sidebar.info(f"현재 {len(filtered_indices)}개의 문항이 존재합니다.")

# 해당 연도·과목만 JSONL 다운로드
st.sidebar.markdown("### 📥 JSONL 다운로드")
if filtered_indices and selected_subject != "과목 없음":
    filtered_entries = [all_data[i] for i in filtered_indices]
    jsonl_lines = [json.dumps(entry, ensure_ascii=False) for entry in filtered_entries]
    jsonl_content = "\n".join(jsonl_lines)
    safe_subject = selected_subject.replace(" ", "_")
    download_filename = f"cpa_{selected_year}_{safe_subject}.jsonl"
    st.sidebar.download_button(
        f"📄 {selected_year}년 {selected_subject} JSONL",
        data=jsonl_content,
        file_name=download_filename,
        mime="application/x-ndjson",
        key="sidebar_download_jsonl",
    )
    st.sidebar.caption("선택한 연도·과목 문항만 저장됩니다.")
else:
    st.sidebar.caption("연도·과목을 선택하면 JSONL 다운로드가 가능합니다.")

# 통계 정보 추가
st.sidebar.markdown("### 📊 데이터 통계")
st.sidebar.text(f"전체 데이터: {len(all_data)}개")
st.sidebar.text(f"전체 연도: {len(years)}개")
st.sidebar.text(f"현재 연도 과목: {len(subjects_in_year)}개")

# ── 검토 진행률 ──
st.sidebar.markdown("---")
st.sidebar.markdown("### ✅ 검토 진행률")

# 현재 연도·과목 진행률
total_cur, done_cur = get_review_stats(all_data, review_status, year=selected_year, subject=selected_subject)
if total_cur > 0:
    pct_cur = done_cur / total_cur
    st.sidebar.progress(pct_cur, text=f"{selected_year}년 {selected_subject}: {done_cur}/{total_cur} ({pct_cur*100:.0f}%)")
else:
    st.sidebar.caption("문항 없음")

# 현재 연도 전체 진행률
total_year, done_year = get_review_stats(all_data, review_status, year=selected_year)
if total_year > 0:
    pct_year = done_year / total_year
    st.sidebar.progress(pct_year, text=f"{selected_year}년 전체: {done_year}/{total_year} ({pct_year*100:.0f}%)")

# 전체 진행률
total_all, done_all = get_review_stats(all_data, review_status)
if total_all > 0:
    pct_all = done_all / total_all
    st.sidebar.progress(pct_all, text=f"전체: {done_all}/{total_all} ({pct_all*100:.0f}%)")

# ── 캐시 / 세션 초기화 ──
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 캐시·세션 관리")
cache_col1, cache_col2 = st.sidebar.columns(2)
with cache_col1:
    if st.button("🔄 캐시 초기화", key="btn_clear_cache", use_container_width=True,
                 help="파일을 다시 읽어 최신 데이터로 새로고침합니다."):
        st.cache_data.clear()
        for k in ['data', 'manual_check_status', 'review_status']:
            if k in st.session_state:
                del st.session_state[k]
        st.toast("캐시 초기화 완료! 새로고침합니다.", icon="🔄")
        st.rerun()
with cache_col2:
    if st.button("🗑️ 검토 초기화", key="btn_clear_review", use_container_width=True,
                 help="모든 문항의 검토 체크를 초기화합니다."):
        st.session_state['review_status'] = {}
        save_review_status({})
        st.toast("검토 상태 초기화 완료!", icon="🗑️")
        st.rerun()

# 누락된 문항 정보 표시
st.sidebar.markdown("---")
st.sidebar.markdown("### ⚠️ 누락된 문항 정보")

missing_data = load_error_report()

if missing_data and selected_year in missing_data:
    year_missing = missing_data[selected_year]
    
    # 현재 선택된 과목의 누락 정보 확인
    found_subject = None
    for subj_key in year_missing.keys():
        if match_subject(selected_subject, subj_key):
            found_subject = subj_key
            break
    
    if found_subject and year_missing[found_subject]:
        missing_nums = year_missing[found_subject]
        
        # 수동 체크 상태 기반으로 완료/미완료 판단
        actually_missing = []
        completed = []
        
        for num in missing_nums:
            if is_manually_checked(selected_year, found_subject, num, manual_check_status):
                completed.append(num)
            else:
                actually_missing.append(num)
        
        st.sidebar.error(f"📌 {found_subject}")
        
        if actually_missing:
            st.sidebar.warning(f"❌ 미완료: {len(actually_missing)}개")
            
            # 미완료 문항 체크 인터페이스
            with st.sidebar.expander("📝 미완료 문항 확인하기"):
                st.caption("문항을 확인했으면 체크하세요")
                
                # 한 번에 여러 문항 선택
                selected_to_check = st.multiselect(
                    "완료 처리할 문항 선택",
                    options=actually_missing,
                    format_func=lambda x: f"{x}번",
                    key=f"check_missing_{selected_year}_{found_subject}"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ 선택 완료", key=f"mark_done_{selected_year}_{found_subject}"):
                        if selected_to_check:
                            for q_num in selected_to_check:
                                key = get_check_key(selected_year, found_subject, q_num)
                                st.session_state['manual_check_status'][key] = True
                            
                            if save_manual_check_status(st.session_state['manual_check_status']):
                                st.success(f"{len(selected_to_check)}개 문항 완료 처리됨!")
                                st.rerun()
                        else:
                            st.warning("문항을 선택하세요")
        else:
            st.sidebar.success("✅ 모두 완료!")
        
        # 완료된 문항도 표시
        if completed:
            st.sidebar.success(f"✅ 완료됨: {len(completed)}개")
            
            # 완료 취소 인터페이스
            with st.sidebar.expander("🔄 완료된 문항 취소하기"):
                st.caption("잘못 체크한 문항을 취소할 수 있습니다")
                
                selected_to_uncheck = st.multiselect(
                    "취소할 문항 선택",
                    options=completed,
                    format_func=lambda x: f"{x}번",
                    key=f"uncheck_completed_{selected_year}_{found_subject}"
                )
                
                if st.button("❌ 선택 취소", key=f"mark_undone_{selected_year}_{found_subject}"):
                    if selected_to_uncheck:
                        for q_num in selected_to_uncheck:
                            key = get_check_key(selected_year, found_subject, q_num)
                            if key in st.session_state['manual_check_status']:
                                del st.session_state['manual_check_status'][key]
                        
                        if save_manual_check_status(st.session_state['manual_check_status']):
                            st.success(f"{len(selected_to_uncheck)}개 문항 취소됨!")
                            st.rerun()
                    else:
                        st.warning("문항을 선택하세요")
    else:
        st.sidebar.success("✅ 누락 없음")
else:
    st.sidebar.info("오류 리포트 정보 없음")

# ==========================================
# 🖥️ 메인 UI Layout
# ==========================================
st.title(f"🛠️ {selected_year}년 {selected_subject} 데이터 수정")

# 탭으로 구성: PDF 뷰어 + 편집기, 오류 리포트
main_tab1, main_tab2 = st.tabs(["📝 문항 편집", "📋 오류 리포트 전체보기"])

with main_tab1:
    # PDF 표시 토글 (기본 OFF → 편집기 전체 너비)
    _show_pdf = st.toggle("📄 PDF 원문 함께 보기", value=False, key="toggle_pdf_view")

    if _show_pdf:
        col_pdf, col_edit = st.columns([1, 1])
    else:
        col_edit = st.container()

    # ---------------------------------------------------------
    # [왼쪽] PDF 뷰어 — 토글 ON일 때만 표시
    # ---------------------------------------------------------
    if _show_pdf:
      with col_pdf:
        st.header("📄 PDF 원문")
        
        if selected_subject == '과목 없음':
            st.warning("선택된 과목이 없습니다.")
        else:
            # PDF 소스 선택
            pdf_source = st.radio(
                "PDF 소스",
                ["자동 검색", "업로드된 파일"],
                horizontal=True,
                key="pdf_source_select"
            )
            
            # 문제 PDF와 정답 PDF를 탭으로 구분
            pdf_tab1, pdf_tab2 = st.tabs(["📝 문제", "✅ 정답"])
            
            # ===== 문제 PDF 탭 =====
            with pdf_tab1:
                pdf_path = None
                msg = None
                
                if pdf_source == "업로드된 파일":
                    # 업로드된 파일 사용
                    if 'uploaded_pdf_path' in st.session_state and 'latest' in st.session_state['uploaded_pdf_path']:
                        pdf_path = st.session_state['uploaded_pdf_path']['latest']
                        if os.path.exists(pdf_path):
                            msg = "Success"
                            st.info(f"📤 업로드: {os.path.basename(pdf_path)}")
                        else:
                            msg = "업로드된 파일을 찾을 수 없습니다."
                    else:
                        st.warning("업로드된 PDF가 없습니다. 사이드바에서 PDF를 업로드하세요.")
                else:
                    # 자동 검색
                    pdf_path, msg = find_pdf_path(selected_year, selected_subject)
                
                if pdf_path and msg == "Success":
                    if pdf_source == "자동 검색":
                        st.success(f"✅ {os.path.basename(pdf_path)}")
                    
                    # PDF 뷰어 표시
                    pdf_html, success = display_pdf(pdf_path)
                    
                    if success:
                        st.markdown(pdf_html, unsafe_allow_html=True)
                        
                        # 텍스트 추출 옵션 (접기)
                        with st.expander("📝 텍스트로 보기 (복사용)"):
                            pdf_text = extract_text_from_pdf(pdf_path)
                            
                            if not pdf_text.startswith("PDF"):
                                # 검색 기능
                                search_term = st.text_input(
                                    "텍스트 검색", 
                                    placeholder="예: 21.",
                                    key="pdf_text_search_question"
                                )
                                
                                display_text = pdf_text
                                if search_term and search_term.strip():
                                    idx = pdf_text.find(search_term.strip())
                                    if idx != -1:
                                        start = max(0, idx - 300)
                                        end = min(len(pdf_text), idx + 3000)
                                        display_text = pdf_text[start:end]
                                        st.info(f"찾음: {idx}/{len(pdf_text)}")
                                    else:
                                        st.warning("못 찾음")
                                        display_text = pdf_text[:2000]
                                else:
                                    display_text = pdf_text[:2000]
                                
                                st.text_area(
                                    "추출된 텍스트", 
                                    value=display_text, 
                                    height=400,
                                    key="pdf_text_display_question"
                                )
                                
                                st.download_button(
                                    "📥 전체 텍스트 다운로드",
                                    data=pdf_text,
                                    file_name=f"{selected_year}_{selected_subject}_문제.txt",
                                    mime="text/plain",
                                    key="download_question_text"
                                )
                            else:
                                st.error(pdf_text)
                    else:
                        st.error(pdf_html)
                elif msg:
                    st.error(f"❌ PDF 파일을 찾을 수 없습니다.\n\n{msg}")
            
            # ===== 정답 PDF 탭 =====
            with pdf_tab2:
                answer_path, answer_msg = find_answer_pdf_path(selected_year)
                
                if answer_path and answer_msg == "Success":
                    st.success(f"✅ {os.path.basename(answer_path)}")
                    
                    # 정답 PDF 뷰어 표시
                    answer_html, answer_success = display_pdf(answer_path)
                    
                    if answer_success:
                        st.markdown(answer_html, unsafe_allow_html=True)
                        
                        # 텍스트 추출 옵션 (접기)
                        with st.expander("📝 텍스트로 보기 (복사용)"):
                            answer_text = extract_text_from_pdf(answer_path)
                            
                            if not answer_text.startswith("PDF"):
                                # 검색 기능
                                search_term_answer = st.text_input(
                                    "텍스트 검색", 
                                    placeholder="예: 경제원론",
                                    key="pdf_text_search_answer"
                                )
                                
                                display_text_answer = answer_text
                                if search_term_answer and search_term_answer.strip():
                                    idx = answer_text.find(search_term_answer.strip())
                                    if idx != -1:
                                        start = max(0, idx - 300)
                                        end = min(len(answer_text), idx + 3000)
                                        display_text_answer = answer_text[start:end]
                                        st.info(f"찾음: {idx}/{len(answer_text)}")
                                    else:
                                        st.warning("못 찾음")
                                        display_text_answer = answer_text[:2000]
                                else:
                                    display_text_answer = answer_text[:2000]
                                
                                st.text_area(
                                    "추출된 텍스트", 
                                    value=display_text_answer, 
                                    height=400,
                                    key="pdf_text_display_answer"
                                )
                                
                                st.download_button(
                                    "📥 전체 텍스트 다운로드",
                                    data=answer_text,
                                    file_name=f"{selected_year}_정답.txt",
                                    mime="text/plain",
                                    key="download_answer_text"
                                )
                            else:
                                st.error(answer_text)
                    else:
                        st.error(answer_html)
                elif answer_msg:
                    st.warning(f"⚠️ 정답 PDF를 찾을 수 없습니다.\n\n{answer_msg}")
                    st.info("💡 정답 PDF는 연도별로 전체 과목의 정답이 포함되어 있습니다.")

    # ---------------------------------------------------------
    # 데이터 수정 및 추가 (JSON 에디터) — PDF OFF 시 전체 너비 사용
    # ---------------------------------------------------------
    with col_edit:
        st.header("✏️ 데이터 편집")
        
        # 누락된 문항 정보 미리 로드
        missing_data = load_error_report()
        current_missing = []
        
        if missing_data and selected_year in missing_data:
            for subj_key, nums in missing_data[selected_year].items():
                if selected_subject in subj_key or subj_key in selected_subject:
                    current_missing = nums
                    break
        
        # 누락 문항 헤더에 표시
        if current_missing:
            # 수동 체크 상태 확인 (found_subject 찾기)
            found_subject_for_check = None
            if missing_data and selected_year in missing_data:
                for subj_key in missing_data[selected_year].keys():
                    if match_subject(selected_subject, subj_key):
                        found_subject_for_check = subj_key
                        break
            
            # 수동 체크 기반으로 완료/미완료 판단
            actually_missing = []
            completed = []
            
            for num in current_missing:
                if found_subject_for_check and is_manually_checked(selected_year, found_subject_for_check, num, manual_check_status):
                    completed.append(num)
                else:
                    actually_missing.append(num)
            
            completion_rate = (len(completed) / len(current_missing) * 100) if current_missing else 0
            
            if actually_missing:
                st.warning(f"🟡 **오류 리포트 진행률**: {completion_rate:.0f}% ({len(completed)}/{len(current_missing)}) | 남은 문항: {len(actually_missing)}개")
            else:
                st.success(f"✅ **오류 리포트 문항 모두 완료!** ({len(completed)}/{len(current_missing)})")
        else:
            st.success("✅ 오류 리포트에 누락 문항 없음")
        
        tab1, tab2, tab3 = st.tabs(["📝 기존 문항 수정", "➕ 신규 문항 추가", "📋 정답표 vs 데이터 일치"])
    
        # 1. 기존 문항 수정 탭
        with tab1:
            if filtered_indices:
                try:
                    # 문항 선택 - 안전한 딕셔너리 생성
                    q_options = {}
                    for i in filtered_indices:
                        try:
                            q_num = all_data[i].get('metadata', {}).get('question_number')
                            if q_num is not None:
                                q_options[q_num] = i
                        except Exception:
                            continue
                    
                    if not q_options:
                        st.warning("유효한 문항 번호를 가진 데이터가 없습니다.")
                    else:
                        # 존재하는 문항 번호와 누락된 문항 번호 표시
                        existing_nums = sorted(q_options.keys())

                        st.info(f"📊 현재 존재하는 문항: **{len(existing_nums)}개**")

                        # 문항 선택 상태 키
                        value_key = "edit_q_select_main_value"
                        select_key = "edit_q_select_main_widget"

                        # 버튼 선택을 위한 기본값 보장
                        if (
                            value_key not in st.session_state
                            or st.session_state[value_key] not in existing_nums
                        ):
                            st.session_state[value_key] = existing_nums[0]

                        # 문항 번호 버튼 선택 (스크롤 선택 유지) — 검토 완료 항목은 ✅ 표시
                        with st.expander("🖱️ 문항 번호 빠른 선택 (버튼)", expanded=False):
                            st.caption("버튼으로 문항 번호를 빠르게 선택할 수 있습니다. ✅ = 검토 완료")
                            cols_per_row = 10
                            for i in range(0, len(existing_nums), cols_per_row):
                                cols = st.columns(cols_per_row)
                                for j, num in enumerate(existing_nums[i : i + cols_per_row]):
                                    is_selected = st.session_state.get(value_key) == num
                                    # 검토 완료 여부 확인
                                    _uid = q_options.get(num)
                                    _uid_str = all_data[_uid].get('unique_id', '') if _uid is not None else ''
                                    _is_reviewed = review_status.get(_uid_str, {}).get('checked', False)
                                    label = f"✅{num}" if _is_reviewed else f"{num}번"
                                    btn_kwargs = {"use_container_width": True}
                                    if is_selected:
                                        btn_kwargs["type"] = "primary"
                                    if cols[j].button(label, key=f"qbtn_{num}", **btn_kwargs):
                                        st.session_state[value_key] = num
                                        st.session_state['_from_nav'] = True

                        # 셀렉트박스 동기화: 이전/다음·버튼으로 바꾼 경우에만 value_key → select_key 반영
                        if st.session_state.get('_from_nav'):
                            st.session_state[select_key] = st.session_state[value_key]
                            st.session_state['_from_nav'] = False
                        elif select_key not in st.session_state or st.session_state.get(select_key) not in existing_nums:
                            st.session_state[select_key] = st.session_state[value_key]
                        
                        # 누락 문항 빠른 확인
                        if current_missing:
                            # 수동 체크 상태 확인
                            found_subject_check = None
                            if missing_data and selected_year in missing_data:
                                for subj_key in missing_data[selected_year].keys():
                                    if match_subject(selected_subject, subj_key):
                                        found_subject_check = subj_key
                                        break
                            
                            # 수동 체크 기반으로 완료/미완료 판단
                            actually_missing = []
                            completed = []
                            
                            for num in current_missing:
                                if found_subject_check and is_manually_checked(selected_year, found_subject_check, num, manual_check_status):
                                    completed.append(num)
                                else:
                                    actually_missing.append(num)
                            
                            completion_rate = (len(completed) / len(current_missing) * 100) if current_missing else 0
                            
                            with st.expander(f"⚠️ 오류 리포트 문항 진행 상황 ({completion_rate:.0f}% 완료)"):
                                # 미완료 문항
                                if actually_missing:
                                    st.markdown(f"**❌ 미완료 ({len(actually_missing)}개)**")
                                    cols_per_row = 10
                                    for i in range(0, len(actually_missing), cols_per_row):
                                        cols = st.columns(cols_per_row)
                                        for j, num in enumerate(actually_missing[i:i+cols_per_row]):
                                            with cols[j]:
                                                st.markdown(f'<span style="color:red">**{num}번**</span>', unsafe_allow_html=True)
                                    st.markdown("---")
                                
                                # 완료된 문항
                                if completed:
                                    st.markdown(f"**✅ 완료됨 ({len(completed)}개)**")
                                    cols_per_row = 10
                                    for i in range(0, len(completed), cols_per_row):
                                        cols = st.columns(cols_per_row)
                                        for j, num in enumerate(completed[i:i+cols_per_row]):
                                            with cols[j]:
                                                st.markdown(f'<span style="color:green">**{num}번**</span>', unsafe_allow_html=True)
                        
                        st.markdown("---")
                        
                        # 문항 선택
                        col_select, col_info = st.columns([2, 1])
                        
                        with col_select:
                            # selectbox에 검토 완료 표시
                            def _fmt_q(x):
                                _idx = q_options.get(x)
                                _uid = all_data[_idx].get('unique_id', '') if _idx is not None else ''
                                _done = review_status.get(_uid, {}).get('checked', False)
                                return f"✅ {x}번 문항" if _done else f"   {x}번 문항"

                            selected_q_num = st.selectbox(
                                "📝 수정할 문항 번호 선택", 
                                options=existing_nums,
                                format_func=_fmt_q,
                                key=select_key,
                            )
                            # selectbox에서 사용자가 직접 선택했으면 value_key에 반영
                            if st.session_state[select_key] != st.session_state[value_key]:
                                st.session_state[value_key] = st.session_state[select_key]
                                st.rerun()
                        
                        with col_info:
                            selected_q_num = st.session_state.get(value_key, selected_q_num)
                            st.metric("선택된 문항", f"{selected_q_num}번")
                            # 좌우 이동 버튼
                            try:
                                current_idx = existing_nums.index(selected_q_num)
                            except ValueError:
                                current_idx = 0
                            prev_num = existing_nums[current_idx - 1] if current_idx > 0 else None
                            next_num = (
                                existing_nums[current_idx + 1]
                                if current_idx + 1 < len(existing_nums)
                                else None
                            )
                            nav_cols = st.columns(3)
                            with nav_cols[0]:
                                if st.button(
                                    "◀ 이전",
                                    key="nav_prev_question",
                                    use_container_width=True,
                                    disabled=prev_num is None,
                                ):
                                    st.session_state[value_key] = prev_num
                                    st.session_state['_from_nav'] = True
                                    st.rerun()
                            with nav_cols[1]:
                                if st.button(
                                    "다음 ▶",
                                    key="nav_next_question",
                                    use_container_width=True,
                                    disabled=next_num is None,
                                ):
                                    st.session_state[value_key] = next_num
                                    st.session_state['_from_nav'] = True
                                    st.rerun()
                            with nav_cols[2]:
                                # 미검토 문항으로 바로 이동
                                _unreviewed = [
                                    n for n in existing_nums
                                    if not review_status.get(
                                        all_data[q_options[n]].get('unique_id', ''), {}
                                    ).get('checked', False)
                                ]
                                if st.button(
                                    f"⏭ 미검토({len(_unreviewed)})",
                                    key="nav_next_unreviewed",
                                    use_container_width=True,
                                    disabled=len(_unreviewed) == 0,
                                    help="아직 검토하지 않은 다음 문항으로 이동",
                                ):
                                    if _unreviewed:
                                        _after = [n for n in _unreviewed if n > selected_q_num]
                                        _target = _after[0] if _after else _unreviewed[0]
                                        st.session_state[value_key] = _target
                                        st.session_state['_from_nav'] = True
                                        st.rerun()
                        
                        # 선택된 문항 데이터 로드
                        if selected_q_num in q_options:
                            target_idx = q_options[selected_q_num]
                            target_data = all_data[target_idx]
                            
                            # ── 검토 완료 체크박스 ──
                            _cur_uid = target_data.get('unique_id', '')
                            _cur_reviewed = review_status.get(_cur_uid, {}).get('checked', False)
                            _review_cb = st.checkbox(
                                f"✅ {selected_q_num}번 문항 검토 완료",
                                value=_cur_reviewed,
                                key=f"review_cb_{_cur_uid}",
                            )
                            if _review_cb != _cur_reviewed:
                                if _review_cb:
                                    st.session_state['review_status'][_cur_uid] = {
                                        'checked': True,
                                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    }
                                else:
                                    if _cur_uid in st.session_state['review_status']:
                                        del st.session_state['review_status'][_cur_uid]
                                save_review_status(st.session_state['review_status'])
                                st.rerun()
                            
                            # 문항 내용 보기 + 편집 통합 UI
                            _conv = target_data.get('conversation', [])
                            _meta = target_data.get('metadata', {})
                            _uid_display = target_data.get('unique_id', '')

                            # ── 메타데이터 요약 ──
                            _meta_cols = st.columns(4)
                            _meta_cols[0].markdown(f"**연도**: {_meta.get('year', '-')}")
                            _meta_cols[1].markdown(f"**과목**: {_meta.get('subject', '-')}")
                            _meta_cols[2].markdown(f"**문항**: {_meta.get('question_number', '-')}번")
                            _meta_cols[3].markdown(f"**ID**: `{_uid_display}`")

                            # ── 문제 내용 (user) 편집 ──
                            _user_content = _conv[0].get('content', '') if len(_conv) > 0 else ''
                            st.markdown("#### 📝 문제 내용")
                            edited_user = st.text_area(
                                "문제 (user)",
                                value=_user_content,
                                height=300,
                                key=f"edit_user_{selected_q_num}",
                                label_visibility="collapsed",
                            )

                            # ── 정답 (assistant) 편집 ──
                            _asst_content = _conv[1].get('content', '') if len(_conv) > 1 else ''
                            st.markdown("#### ✅ 정답")
                            edited_answer = st.text_area(
                                "정답 (assistant)",
                                value=_asst_content,
                                height=68,
                                key=f"edit_asst_{selected_q_num}",
                                label_visibility="collapsed",
                            )

                            # ── 전체 JSON 편집 (고급) ──
                            with st.expander("🔧 전체 JSON 편집 (고급)", expanded=False):
                                edited_json = st.text_area(
                                    f"{selected_q_num}번 전체 JSON",
                                    value=json.dumps(target_data, indent=2, ensure_ascii=False),
                                    height=400,
                                    key=f"edit_json_{selected_q_num}",
                                    label_visibility="collapsed",
                                )

                            # ── 저장 버튼 ──
                            col_save, col_json_save, col_spacer = st.columns([1, 1, 2])

                            with col_save:
                                if st.button("💾 저장", key="save_edit", type="primary", use_container_width=True):
                                    try:
                                        # 위의 문제/정답 필드로 새 entry 구성
                                        new_entry = json.loads(json.dumps(target_data))  # deep copy
                                        if len(new_entry.get('conversation', [])) > 0:
                                            new_entry['conversation'][0]['content'] = edited_user
                                        if len(new_entry.get('conversation', [])) > 1:
                                            new_entry['conversation'][1]['content'] = edited_answer

                                        is_valid, msg = validate_entry(new_entry)
                                        if not is_valid:
                                            st.error(f"❌ 검증 실패: {msg}")
                                        else:
                                            st.session_state['data'][target_idx] = new_entry
                                            if save_data_to_file(st.session_state['data']):
                                                _saved_uid = new_entry.get('unique_id', '')
                                                if _saved_uid:
                                                    st.session_state['review_status'][_saved_uid] = {
                                                        'checked': True,
                                                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                    }
                                                    save_review_status(st.session_state['review_status'])
                                                st.toast(f"✅ {selected_q_num}번 저장 완료!", icon="✅")
                                                st.success("저장되었습니다!")
                                                st.rerun()
                                            else:
                                                st.error("파일 저장 실패")
                                    except Exception as e:
                                        st.error(f"❌ 오류: {e}")

                            with col_json_save:
                                if st.button("💾 JSON 저장", key="save_json_edit", use_container_width=True,
                                             help="'전체 JSON 편집' 내용으로 저장합니다"):
                                    try:
                                        new_entry = json.loads(edited_json)
                                        is_valid, msg = validate_entry(new_entry)
                                        if not is_valid:
                                            st.error(f"❌ 검증 실패: {msg}")
                                        else:
                                            st.session_state['data'][target_idx] = new_entry
                                            if save_data_to_file(st.session_state['data']):
                                                _saved_uid = new_entry.get('unique_id', '')
                                                if _saved_uid:
                                                    st.session_state['review_status'][_saved_uid] = {
                                                        'checked': True,
                                                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                    }
                                                    save_review_status(st.session_state['review_status'])
                                                st.toast(f"✅ {selected_q_num}번 JSON 저장 완료!", icon="✅")
                                                st.success("저장되었습니다!")
                                                st.rerun()
                                            else:
                                                st.error("파일 저장 실패")
                                    except json.JSONDecodeError as je:
                                        st.error(f"❌ JSON 형식 오류: {je}")
                                    except Exception as e:
                                        st.error(f"❌ 오류: {e}")
                        else:
                            st.error(f"문항 {selected_q_num}번을 찾을 수 없습니다.")
                                
                except Exception as e:
                    st.error(f"문항 편집 UI 로딩 중 오류: {e}")
            else:
                st.info("이 과목에 등록된 문항이 없습니다. '신규 문항 추가' 탭을 이용하세요.")

        # 2. 신규 문항 추가 탭 (누락된 문제 복구용)
        with tab2:
            st.markdown("##### ➕ 누락된 문제 추가")
            
            # 누락된 문항 정보 표시
            missing_data = load_error_report()
            current_missing = []
            
            if missing_data and selected_year in missing_data:
                for subj_key, nums in missing_data[selected_year].items():
                    if match_subject(selected_subject, subj_key):
                        current_missing = nums
                        break
            
            if current_missing:
                # 수동 체크 상태 확인
                found_subject_add = None
                if missing_data and selected_year in missing_data:
                    for subj_key in missing_data[selected_year].keys():
                        if match_subject(selected_subject, subj_key):
                            found_subject_add = subj_key
                            break
                
                # 수동 체크 기반으로 완료/미완료 판단
                actually_missing = []
                completed = []
                
                for num in current_missing:
                    if found_subject_add and is_manually_checked(selected_year, found_subject_add, num, manual_check_status):
                        completed.append(num)
                    else:
                        actually_missing.append(num)
                
                completion_rate = (len(completed) / len(current_missing) * 100) if current_missing else 0
                
                if actually_missing:
                    st.error(f"⚠️ **오류 리포트 문항 진행률**: {completion_rate:.0f}% ({len(completed)}/{len(current_missing)})")
                else:
                    st.success(f"✅ **오류 리포트 문항 모두 완료!** ({len(completed)}/{len(current_missing)})")
                
                # 미완료 문항을 그리드로 표시
                if actually_missing:
                    st.markdown("**❌ 미완료 문항:**")
                    cols_per_row = 10
                    for i in range(0, len(actually_missing), cols_per_row):
                        cols = st.columns(cols_per_row)
                        for j, num in enumerate(actually_missing[i:i+cols_per_row]):
                            with cols[j]:
                                st.markdown(f'<span style="color:red">**{num}번**</span>', unsafe_allow_html=True)
                
                # 완료된 문항 표시
                if completed:
                    with st.expander(f"✅ 완료된 문항 {len(completed)}개 보기"):
                        cols_per_row = 10
                        for i in range(0, len(completed), cols_per_row):
                            cols = st.columns(cols_per_row)
                            for j, num in enumerate(completed[i:i+cols_per_row]):
                                with cols[j]:
                                    st.markdown(f'<span style="color:green">**{num}번**</span>', unsafe_allow_html=True)
            else:
                st.success("✅ 오류 리포트에 누락된 문항이 없습니다!")
            
            st.markdown("---")
            
            # 탭으로 구분: 단일 입력 vs 대량 입력
            add_tab1, add_tab2 = st.tabs(["📝 단일 문항 추가", "📦 대량 JSON 입력 (Gemini 추출)"])
            
            # ========================================
            # 단일 문항 추가 탭
            # ========================================
            with add_tab1:
                st.markdown("**작업 순서:**")
                st.markdown("1. 왼쪽 PDF에서 누락된 문제 텍스트를 복사합니다.")
                st.markdown("2. 아래 **프롬프트 생성기**에 붙여넣고 AI에게 포맷팅을 요청하세요.")
                st.markdown("3. AI가 준 JSON을 아래 입력창에 넣고 추가하세요.")
                
                # AI 프롬프트 생성기
                raw_text_input = st.text_area(
                    "PDF에서 복사한 텍스트 붙여넣기 (프롬프트 생성용)", 
                    height=150,
                    key="raw_text_input_single"
                )
                
                if raw_text_input and raw_text_input.strip():
                    # 안전한 변수 처리
                    safe_year = selected_year if selected_year != 'Unknown' else 'XXXX'
                    safe_subject = selected_subject if selected_subject not in ['Unknown', '과목 없음'] else '과목명'
                    
                    prompt = f"""
다음은 {safe_year}년 {safe_subject} 과목의 문제입니다. 
아래 텍스트를 읽고 JSON 포맷으로 변환해주세요.

[필수 포맷]
{{
    "conversation": [
        {{"role": "user", "content": "문제 내용 전체..."}},
        {{"role": "assistant", "content": "정답: ⑤"}}
    ],
    "metadata": {{
        "year": "{safe_year}",
        "subject": "{safe_subject}",
        "question_number": (문제번호 숫자),
        "source": "cpa_exam"
    }},
    "unique_id": "cpa_{safe_year}_{safe_subject}_(문제번호)"
}}

[텍스트]
{raw_text_input}
                    """
                    st.code(prompt, language="text")
                    st.caption("▲ 위 내용을 복사해서 AI에게 보내세요.")
                
                st.markdown("---")
                
                # 신규 JSON 입력
                new_json_input = st.text_area(
                    "AI가 만들어준 JSON 붙여넣기", 
                    height=300, 
                    key="new_json_single",
                    placeholder='{"conversation": [...], "metadata": {...}, "unique_id": "..."}'
                )
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    add_button = st.button("새 문항 추가하기", key="add_new_single", type="primary")
                with col2:
                    if st.button("미리보기", key="preview_new_single"):
                        if new_json_input and new_json_input.strip():
                            try:
                                preview_entry = json.loads(new_json_input)
                                st.json(preview_entry)
                            except json.JSONDecodeError as je:
                                st.error(f"JSON 파싱 오류: {je}")
                        else:
                            st.warning("입력된 JSON이 없습니다.")
                
                if add_button:
                    if not new_json_input or not new_json_input.strip():
                        st.error("JSON 데이터를 입력해주세요.")
                    else:
                        try:
                            new_entry = json.loads(new_json_input)
                            
                            # 유효성 검증
                            is_valid, msg = validate_entry(new_entry)
                            if not is_valid:
                                st.error(f"데이터 검증 실패: {msg}")
                            else:
                                # 중복 체크 (unique_id 기준)
                                existing_ids = [d.get('unique_id') for d in st.session_state['data']]
                                new_id = new_entry.get('unique_id')
                                
                                if new_id in existing_ids:
                                    st.warning(f"⚠️ 이미 존재하는 ID입니다: {new_id}")
                                    if st.checkbox("기존 데이터를 덮어쓰시겠습니까?", key="overwrite_check_single"):
                                        # 기존 항목 찾아서 교체
                                        for idx, d in enumerate(st.session_state['data']):
                                            if d.get('unique_id') == new_id:
                                                st.session_state['data'][idx] = new_entry
                                                break
                                        
                                        if save_data_to_file(st.session_state['data']):
                                            st.toast("문항 덮어쓰기 완료!", icon="✅")
                                            st.rerun()
                                else:
                                    # 새 항목 추가
                                    st.session_state['data'].append(new_entry)
                                    
                                    if save_data_to_file(st.session_state['data']):
                                        st.toast("새 문항 추가 완료!", icon="🎉")
                                        st.success(f"문항 ID '{new_id}'가 추가되었습니다.")
                                        st.rerun()
                                    else:
                                        # 저장 실패 시 롤백
                                        st.session_state['data'].pop()
                                        st.error("파일 저장에 실패했습니다. 데이터가 추가되지 않았습니다.")
                                        
                        except json.JSONDecodeError as je:
                            st.error(f"JSON 파싱 오류: {je}\n\n올바른 JSON 형식인지 확인하세요.")
                        except Exception as e:
                            st.error(f"추가 실패: {type(e).__name__} - {e}")
            
            # ========================================
            # 대량 JSON 입력 탭 (Gemini 추출 데이터)
            # ========================================
            with add_tab2:
                st.markdown("**🤖 Gemini가 추출한 여러 문항을 한번에 붙여넣기**")
                st.info("Gemini가 PDF에서 추출한 JSON 데이터를 여러 줄(JSONL 형식)로 붙여넣으면, 각 문항을 확인하고 선택적으로 추가할 수 있습니다.")
                
                # 대량 JSON 입력
                bulk_json_input = st.text_area(
                    "Gemini가 추출한 JSONL 데이터 붙여넣기",
                    height=400,
                    placeholder='{"conversation": [...], "metadata": {...}, "unique_id": "..."}\n{"conversation": [...], "metadata": {...}, "unique_id": "..."}\n...',
                    key="bulk_json_input",
                    help="각 줄에 하나씩 JSON 객체를 붙여넣으세요. (JSONL 형식)"
                )
                
                if bulk_json_input and bulk_json_input.strip():
                    # JSON 파싱
                    lines = bulk_json_input.strip().split('\n')
                    parsed_questions = []
                    parse_errors = []
                    
                    for line_num, line in enumerate(lines, 1):
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            entry = json.loads(line)
                            is_valid, msg = validate_entry(entry)
                            
                            if is_valid:
                                # 기존 데이터 확인
                                existing_ids = [d.get('unique_id') for d in st.session_state['data']]
                                exists = entry.get('unique_id') in existing_ids
                                
                                # 기존 데이터와 비교할 수 있도록 저장
                                existing_entry = None
                                if exists:
                                    for d in st.session_state['data']:
                                        if d.get('unique_id') == entry.get('unique_id'):
                                            existing_entry = d
                                            break
                                
                                parsed_questions.append({
                                    'line': line_num,
                                    'data': entry,
                                    'exists': exists,
                                    'existing_data': existing_entry,
                                    'question_number': entry.get('metadata', {}).get('question_number', '?')
                                })
                            else:
                                parse_errors.append(f"라인 {line_num}: {msg}")
                        
                        except json.JSONDecodeError as je:
                            parse_errors.append(f"라인 {line_num}: JSON 파싱 오류 - {str(je)[:100]}")
                        except Exception as e:
                            parse_errors.append(f"라인 {line_num}: {str(e)[:100]}")
                    
                    # 파싱 결과 표시
                    st.markdown("---")
                    st.markdown(f"### 📊 파싱 결과: {len(parsed_questions)}개 문항")
                    
                    if parse_errors:
                        with st.expander(f"⚠️ 파싱 오류 {len(parse_errors)}개", expanded=False):
                            for error in parse_errors:
                                st.error(error)
                    
                    if parsed_questions:
                        # 문항 선택 및 비교
                        st.markdown("### 🔍 문항 선택 및 비교")
                        
                        # 문항 번호로 선택
                        question_options = {
                            f"{q['question_number']}번 {'⚠️ 기존재함' if q['exists'] else '✅ 신규'}": idx
                            for idx, q in enumerate(parsed_questions)
                        }
                        
                        selected_question = st.selectbox(
                            "비교할 문항 선택",
                            options=list(question_options.keys()),
                            key="bulk_question_select"
                        )
                        
                        selected_idx = question_options[selected_question]
                        selected_q = parsed_questions[selected_idx]
                        
                        st.markdown("---")
                        
                        # 문항 상세 표시
                        if selected_q['exists']:
                            st.warning(f"⚠️ **{selected_q['question_number']}번 문항이 이미 존재합니다.** 아래에서 비교하세요.")
                            
                            col_new, col_existing = st.columns(2)
                            
                            with col_new:
                                st.markdown("#### 🆕 Gemini 추출 데이터")
                                
                                # 문제 내용
                                if 'conversation' in selected_q['data'] and len(selected_q['data']['conversation']) > 0:
                                    st.text_area(
                                        "문제 내용",
                                        value=selected_q['data']['conversation'][0].get('content', '')[:500],
                                        height=200,
                                        disabled=True,
                                        key=f"new_content_{selected_idx}"
                                    )
                                    
                                    if len(selected_q['data']['conversation']) > 1:
                                        gemini_answer = selected_q['data']['conversation'][1].get('content', '')
                                        st.info(f"**Gemini 추출 정답**: {gemini_answer}")
                                
                                with st.expander("전체 JSON 보기"):
                                    st.json(selected_q['data'])
                            
                            with col_existing:
                                st.markdown("#### 📁 기존 데이터")
                                
                                if selected_q['existing_data']:
                                    # 문제 내용
                                    if 'conversation' in selected_q['existing_data'] and len(selected_q['existing_data']['conversation']) > 0:
                                        st.text_area(
                                            "문제 내용",
                                            value=selected_q['existing_data']['conversation'][0].get('content', '')[:500],
                                            height=200,
                                            disabled=True,
                                            key=f"existing_content_{selected_idx}"
                                        )
                                        
                                        if len(selected_q['existing_data']['conversation']) > 1:
                                            existing_answer = selected_q['existing_data']['conversation'][1].get('content', '')
                                            st.success(f"**기존 정답**: {existing_answer}")
                                    
                                    with st.expander("전체 JSON 보기"):
                                        st.json(selected_q['existing_data'])
                            
                            # 정답 수정 영역
                            st.markdown("---")
                            st.markdown("#### ✏️ 정답 수정 (선택사항)")
                            
                            col_answer1, col_answer2 = st.columns([2, 1])
                            
                            with col_answer1:
                                # 기본값: Gemini가 추출한 정답
                                default_answer = ""
                                if len(selected_q['data']['conversation']) > 1:
                                    default_answer = selected_q['data']['conversation'][1].get('content', '')
                                
                                custom_answer = st.text_input(
                                    "정답 입력 (비워두면 Gemini 추출 정답 사용)",
                                    value=default_answer,
                                    placeholder="예: 정답: ③",
                                    key=f"custom_answer_{selected_idx}"
                                )
                            
                            with col_answer2:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.caption("💡 정답이 다르면 직접 입력하세요")
                            
                            # 덮어쓰기 옵션
                            if st.button(f"🔄 {selected_q['question_number']}번 덮어쓰기", key=f"overwrite_{selected_idx}", type="secondary"):
                                # 정답 업데이트
                                updated_data = selected_q['data'].copy()
                                if custom_answer and custom_answer.strip():
                                    # 사용자가 입력한 정답으로 업데이트
                                    if len(updated_data['conversation']) > 1:
                                        updated_data['conversation'][1]['content'] = custom_answer.strip()
                                
                                # 기존 항목 찾아서 교체
                                for idx, d in enumerate(st.session_state['data']):
                                    if d.get('unique_id') == updated_data.get('unique_id'):
                                        st.session_state['data'][idx] = updated_data
                                        break
                                
                                if save_data_to_file(st.session_state['data']):
                                    st.toast(f"✅ {selected_q['question_number']}번 덮어쓰기 완료!", icon="✅")
                                    st.rerun()
                        
                        else:
                            st.success(f"✅ **{selected_q['question_number']}번은 신규 문항입니다.**")
                            
                            # 문제 내용 미리보기
                            if 'conversation' in selected_q['data'] and len(selected_q['data']['conversation']) > 0:
                                st.text_area(
                                    "문제 내용",
                                    value=selected_q['data']['conversation'][0].get('content', '')[:500],
                                    height=200,
                                    disabled=True,
                                    key=f"new_only_content_{selected_idx}"
                                )
                                
                                if len(selected_q['data']['conversation']) > 1:
                                    gemini_answer_new = selected_q['data']['conversation'][1].get('content', '')
                                    st.info(f"**Gemini 추출 정답**: {gemini_answer_new}")
                            
                            with st.expander("전체 JSON 보기"):
                                st.json(selected_q['data'])
                            
                            # 정답 수정 영역 (신규 문항)
                            st.markdown("---")
                            st.markdown("#### ✏️ 정답 수정 (선택사항)")
                            
                            col_answer_new1, col_answer_new2 = st.columns([2, 1])
                            
                            with col_answer_new1:
                                # 기본값: Gemini가 추출한 정답
                                default_answer_new = ""
                                if len(selected_q['data']['conversation']) > 1:
                                    default_answer_new = selected_q['data']['conversation'][1].get('content', '')
                                
                                custom_answer_new = st.text_input(
                                    "정답 입력 (비워두면 Gemini 추출 정답 사용)",
                                    value=default_answer_new,
                                    placeholder="예: 정답: ③",
                                    key=f"custom_answer_new_{selected_idx}"
                                )
                            
                            with col_answer_new2:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.caption("💡 정답이 다르면 직접 입력하세요")
                            
                            # 추가 버튼
                            if st.button(f"➕ {selected_q['question_number']}번 추가하기", key=f"add_{selected_idx}", type="primary"):
                                # 정답 업데이트
                                updated_data_new = selected_q['data'].copy()
                                if custom_answer_new and custom_answer_new.strip():
                                    # 사용자가 입력한 정답으로 업데이트
                                    if len(updated_data_new['conversation']) > 1:
                                        updated_data_new['conversation'][1]['content'] = custom_answer_new.strip()
                                
                                st.session_state['data'].append(updated_data_new)
                                
                                if save_data_to_file(st.session_state['data']):
                                    st.toast(f"✅ {selected_q['question_number']}번 추가 완료!", icon="🎉")
                                    st.rerun()
                                else:
                                    # 롤백
                                    st.session_state['data'].pop()
                                    st.error("파일 저장에 실패했습니다.")
                        
                        st.markdown("---")
                        
                        # 일괄 작업
                        st.markdown("### 📦 일괄 작업")
                        
                        # 신규 문항과 기존 문항 필터링
                        new_questions = [q for q in parsed_questions if not q['exists']]
                        existing_questions = [q for q in parsed_questions if q['exists']]
                        
                        col_bulk1, col_bulk2 = st.columns(2)
                        
                        with col_bulk1:
                            # 신규 문항 일괄 추가
                            if new_questions:
                                st.info(f"**신규 문항**: {len(new_questions)}개")
                                
                                if st.button(f"➕ 신규 {len(new_questions)}개 문항 일괄 추가", key="bulk_add_all", type="primary", use_container_width=True):
                                    added_count = 0
                                    
                                    for q in new_questions:
                                        st.session_state['data'].append(q['data'])
                                        added_count += 1
                                    
                                    if save_data_to_file(st.session_state['data']):
                                        st.toast(f"✅ {added_count}개 문항 추가 완료!", icon="🎉")
                                        st.success(f"{added_count}개의 신규 문항이 추가되었습니다.")
                                        st.rerun()
                                    else:
                                        # 롤백
                                        for _ in range(added_count):
                                            st.session_state['data'].pop()
                                        st.error("파일 저장에 실패했습니다.")
                            else:
                                st.info("**신규 문항**: 0개")
                        
                        with col_bulk2:
                            # 기존 문항 일괄 덮어쓰기
                            if existing_questions:
                                st.warning(f"**기존 문항 (중복)**: {len(existing_questions)}개")
                                
                                if st.button(f"🔄 기존 {len(existing_questions)}개 문항 일괄 덮어쓰기", key="bulk_overwrite_all", type="secondary", use_container_width=True):
                                    overwritten_count = 0
                                    
                                    for q in existing_questions:
                                        # 기존 항목 찾아서 교체
                                        for idx, d in enumerate(st.session_state['data']):
                                            if d.get('unique_id') == q['data'].get('unique_id'):
                                                st.session_state['data'][idx] = q['data']
                                                overwritten_count += 1
                                                break
                                    
                                    if save_data_to_file(st.session_state['data']):
                                        st.toast(f"✅ {overwritten_count}개 문항 덮어쓰기 완료!", icon="✅")
                                        st.success(f"{overwritten_count}개의 기존 문항이 업데이트되었습니다.")
                                        st.rerun()
                                    else:
                                        st.error("파일 저장에 실패했습니다.")
                            else:
                                st.success("**중복 문항**: 0개")
                        
                        # 전체 통계
                        st.markdown("---")
                        st.info(f"📊 **전체 통계**: 파싱 성공 {len(parsed_questions)}개 | 신규 {len(new_questions)}개 | 중복 {len(existing_questions)}개")
                        
                        # 정답 일괄 수정 (선택사항)
                        if parsed_questions:
                            with st.expander("✏️ 정답 일괄 수정 (고급)"):
                                st.markdown("모든 문항의 정답을 한번에 확인하고 수정할 수 있습니다.")
                                
                                # 세션 상태에 정답 수정 데이터 저장
                                if 'bulk_answers' not in st.session_state:
                                    st.session_state['bulk_answers'] = {}
                                
                                # 테이블 형식으로 표시
                                for q in parsed_questions:
                                    q_num = q['question_number']
                                    q_id = q['data'].get('unique_id', '')
                                    
                                    # Gemini 추출 정답
                                    gemini_answer = ""
                                    if len(q['data'].get('conversation', [])) > 1:
                                        gemini_answer = q['data']['conversation'][1].get('content', '')
                                    
                                    # 기존 정답 (중복인 경우)
                                    existing_answer = ""
                                    if q['exists'] and q['existing_data']:
                                        if len(q['existing_data'].get('conversation', [])) > 1:
                                            existing_answer = q['existing_data']['conversation'][1].get('content', '')
                                    
                                    # 행 표시
                                    col_q1, col_q2, col_q3, col_q4 = st.columns([1, 2, 2, 3])
                                    
                                    with col_q1:
                                        status = "🆕" if not q['exists'] else "⚠️"
                                        st.markdown(f"{status} **{q_num}번**")
                                    
                                    with col_q2:
                                        st.caption(f"Gemini: {gemini_answer}")
                                    
                                    with col_q3:
                                        if existing_answer:
                                            st.caption(f"기존: {existing_answer}")
                                        else:
                                            st.caption("기존: -")
                                    
                                    with col_q4:
                                        # 초기값 설정
                                        if q_id not in st.session_state['bulk_answers']:
                                            st.session_state['bulk_answers'][q_id] = gemini_answer
                                        
                                        # 정답 수정 입력
                                        modified_answer = st.text_input(
                                            "정답 수정",
                                            value=st.session_state['bulk_answers'][q_id],
                                            key=f"bulk_answer_{q_id}",
                                            label_visibility="collapsed"
                                        )
                                        st.session_state['bulk_answers'][q_id] = modified_answer
                                
                                st.markdown("---")
                                
                                # 일괄 저장 버튼
                                col_save1, col_save2 = st.columns([1, 2])
                                
                                with col_save1:
                                    if st.button("💾 정답 일괄 적용 및 저장", key="bulk_save_answers", type="primary"):
                                        # 모든 문항의 정답 업데이트
                                        updated_count = 0
                                        
                                        for q in parsed_questions:
                                            q_id = q['data'].get('unique_id', '')
                                            
                                            # 수정된 정답 가져오기
                                            if q_id in st.session_state['bulk_answers']:
                                                new_answer = st.session_state['bulk_answers'][q_id]
                                                
                                                # 데이터 복사 및 정답 업데이트
                                                updated_data = q['data'].copy()
                                                if len(updated_data.get('conversation', [])) > 1:
                                                    updated_data['conversation'][1]['content'] = new_answer
                                                
                                                # 신규 or 기존 처리
                                                if q['exists']:
                                                    # 덮어쓰기
                                                    for idx, d in enumerate(st.session_state['data']):
                                                        if d.get('unique_id') == q_id:
                                                            st.session_state['data'][idx] = updated_data
                                                            updated_count += 1
                                                            break
                                                else:
                                                    # 추가
                                                    st.session_state['data'].append(updated_data)
                                                    updated_count += 1
                                        
                                        # 저장
                                        if save_data_to_file(st.session_state['data']):
                                            st.toast(f"✅ {updated_count}개 문항 저장 완료!", icon="🎉")
                                            # 세션 상태 초기화
                                            if 'bulk_answers' in st.session_state:
                                                del st.session_state['bulk_answers']
                                            st.rerun()
                                        else:
                                            st.error("파일 저장에 실패했습니다.")
                                
                                with col_save2:
                                    st.caption("💡 수정한 정답을 모든 문항에 한번에 적용합니다.")
                    
                else:
                    st.info("👆 위 입력창에 Gemini가 추출한 JSONL 데이터를 붙여넣으세요.")

        # 3. 정답표 vs 데이터 일치 확인 탭
        with tab3:
            st.markdown("##### 📋 정답표와 실제 입력된 정답 한번에 비교")
            st.caption("정답표(1 ① 형식) 또는 JSONL(한 줄에 JSON 한 개)을 붙여넣을 수 있습니다. 반영 후 저장 버튼으로 파일에 저장됩니다.")

            answer_key_paste = st.text_area(
                "정답표 / JSONL 붙여넣기",
                placeholder="정답표: 1 ①\\n2 ②\\n3 ③\\n...\\n또는 JSONL: {\"conversation\":[...], \"metadata\":{...}} 한 줄씩",
                height=180,
                key="answer_key_paste"
            )

            # 1) JSON/JSONL 먼저 시도
            jsonl_entries, jsonl_err = parse_jsonl_answer_key(answer_key_paste)
            if jsonl_entries:
                st.success(f"JSONL 인식됨: **{len(jsonl_entries)}개** 문항")
                if st.button("💾 붙여넣은 JSON 데이터로 반영 후 저장", key="tab3_save_jsonl", type="primary"):
                    updated = 0
                    appended = 0
                    for entry in jsonl_entries:
                        uid = entry.get("unique_id")
                        meta = entry.get("metadata") or {}
                        year = str(meta.get("year", ""))
                        subject = meta.get("subject", "")
                        q_num = meta.get("question_number")
                        if uid:
                            for idx, d in enumerate(st.session_state["data"]):
                                if d.get("unique_id") == uid:
                                    st.session_state["data"][idx] = entry
                                    updated += 1
                                    break
                            else:
                                st.session_state["data"].append(entry)
                                appended += 1
                        elif year and subject and q_num is not None:
                            for idx, d in enumerate(st.session_state["data"]):
                                m = d.get("metadata") or {}
                                if (str(m.get("year")) == year and m.get("subject") == subject and m.get("question_number") == q_num):
                                    st.session_state["data"][idx] = entry
                                    updated += 1
                                    break
                            else:
                                st.session_state["data"].append(entry)
                                appended += 1
                        else:
                            st.session_state["data"].append(entry)
                            appended += 1
                    if save_data_to_file(st.session_state["data"]):
                        st.toast(f"저장 완료 (수정 {updated}개, 추가 {appended}개)", icon="✅")
                        st.rerun()
                    else:
                        st.error("파일 저장에 실패했습니다. 권한 또는 경로를 확인하세요.")

            # 2) 일반 정답표 파싱 및 비교 테이블
            answer_key_map = parse_answer_key_text(answer_key_paste) if not jsonl_entries else {}

            # 실제 입력된 정답 수집 (현재 선택된 연도·과목)
            data_answers = {}
            for i in filtered_indices:
                entry = all_data[i]
                meta = entry.get("metadata") or {}
                q_num = meta.get("question_number")
                if q_num is None:
                    continue
                try:
                    q_num = int(q_num)
                except (ValueError, TypeError):
                    continue
                conv = entry.get("conversation") or []
                asst_content = ""
                for m in conv:
                    if m.get("role") == "assistant":
                        asst_content = m.get("content", "")
                        break
                data_answers[q_num] = extract_answer_from_content(asst_content)

            if not jsonl_entries and answer_key_map:
                if st.button("💾 정답표로 정답만 반영 후 저장", key="tab3_save_answer_key", type="primary"):
                    choice_map = {"①": "①", "②": "②", "③": "③", "④": "④", "⑤": "⑤", "1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤"}
                    applied = 0
                    for i in filtered_indices:
                        entry = st.session_state["data"][i]
                        meta = entry.get("metadata") or {}
                        q_num = meta.get("question_number")
                        try:
                            q_num = int(q_num)
                        except (ValueError, TypeError):
                            continue
                        if q_num not in answer_key_map:
                            continue
                        ans = answer_key_map[q_num]
                        ans_str = choice_map.get(ans, ans)
                        conv = entry.get("conversation") or []
                        for m in conv:
                            if m.get("role") == "assistant":
                                m["content"] = f"정답: {ans_str}"
                                applied += 1
                                break
                    if applied and save_data_to_file(st.session_state["data"]):
                        st.toast(f"저장 완료: {applied}개 문항 정답 반영", icon="✅")
                        st.rerun()
                    elif applied:
                        st.error("파일 저장에 실패했습니다.")
                    else:
                        st.warning("반영할 문항이 없습니다. 정답표 형식(1 ①)을 확인하세요.")

            if not data_answers:
                st.info("현재 선택한 연도·과목에 문항 데이터가 없습니다.")
            else:
                st.markdown("###### 비교 결과 (정답표 칸을 직접 입력·수정할 수 있습니다)")
                all_nums = sorted(set(list(data_answers.keys()) + list(answer_key_map.keys())))
                rows = []
                match_count = 0
                for q_num in all_nums:
                    key_ans = answer_key_map.get(q_num, "")
                    data_ans = data_answers.get(q_num, "")
                    key_n = normalize_answer_for_compare(key_ans)
                    data_n = normalize_answer_for_compare(data_ans)
                    is_match = (key_n == data_n) if (key_n and data_n) else None
                    if is_match is True:
                        match_count += 1
                    status = "✅ 일치" if is_match is True else ("❌ 불일치" if is_match is False else "─")
                    rows.append({
                        "문항": q_num,
                        "정답표": key_ans if key_ans else "",
                        "실제 입력된 정답": data_ans if data_ans else "-",
                        "일치": status,
                    })
                df_compare = pd.DataFrame(rows)
                choice_map = {"①": "①", "②": "②", "③": "③", "④": "④", "⑤": "⑤", "1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤"}
                edited_df = st.data_editor(
                    df_compare,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "문항": st.column_config.NumberColumn("문항", disabled=True),
                        "정답표": st.column_config.TextColumn("정답표 (①~⑤ 또는 1~5 입력)", help="여기에 정답을 입력하세요"),
                        "실제 입력된 정답": st.column_config.TextColumn("실제 입력된 정답", disabled=True),
                        "일치": st.column_config.TextColumn("일치", disabled=True),
                    },
                    key="tab3_answer_editor",
                )
                st.caption("💡 정답표 칸에 ① ② ③ ④ ⑤ 또는 1 2 3 4 5 를 넣은 뒤 아래 버튼으로 저장하세요.")
                if st.button("💾 편집한 정답표로 반영 후 저장", key="tab3_save_edited", type="primary"):
                    applied = 0
                    for _, row in edited_df.iterrows():
                        q_num = row.get("문항")
                        key_ans = (row.get("정답표") or "").strip()
                        if q_num is None or not key_ans:
                            continue
                        try:
                            q_num = int(q_num)
                        except (ValueError, TypeError):
                            continue
                        ans_str = choice_map.get(key_ans, key_ans)
                        if ans_str not in ("①", "②", "③", "④", "⑤"):
                            continue
                        for i in filtered_indices:
                            entry = st.session_state["data"][i]
                            meta = entry.get("metadata") or {}
                            if meta.get("question_number") != q_num:
                                continue
                            conv = entry.get("conversation") or []
                            for m in conv:
                                if m.get("role") == "assistant":
                                    m["content"] = f"정답: {ans_str}"
                                    applied += 1
                                    break
                            break
                    if applied and save_data_to_file(st.session_state["data"]):
                        st.toast(f"저장 완료: {applied}개 문항 정답 반영", icon="✅")
                        st.rerun()
                    elif applied:
                        st.error("파일 저장에 실패했습니다.")
                    else:
                        st.warning("반영할 정답이 없습니다. 정답표 칸에 ①~⑤ 또는 1~5를 입력했는지 확인하세요.")
                total = len([r for r in rows if r["일치"] != "─"])
                if total:
                    st.caption(f"일치: {match_count}개 / 비교 가능: {total}개 (전체 문항: {len(rows)}개)")

# ---------------------------------------------------------
# [오류 리포트 탭]
# ---------------------------------------------------------
with main_tab2:
    st.header("📋 오류 리포트 전체보기")
    
    if os.path.exists(ERROR_REPORT_FILE):
        try:
            with open(ERROR_REPORT_FILE, 'r', encoding='utf-8') as f:
                error_content = f.read()
            
            # 마크다운으로 표시
            st.markdown(error_content)
            
            # 다운로드 버튼
            st.download_button(
                "📥 오류 리포트 다운로드",
                data=error_content,
                file_name="error_report.md",
                mime="text/markdown"
            )
            
        except Exception as e:
            st.error(f"오류 리포트 로드 실패: {e}")
    else:
        st.warning(f"오류 리포트 파일을 찾을 수 없습니다: {ERROR_REPORT_FILE}")
    
    st.markdown("---")
    
    # 파싱된 데이터 표시
    st.subheader("📊 누락 문항 진행 상황")
    
    missing_data = load_error_report()
    
    if missing_data:
        # 연도별 통계
        for year in sorted(missing_data.keys()):
            # 해당 연도의 전체 통계 계산
            year_total_missing = 0
            year_total_completed = 0
            
            for subject, nums in missing_data[year].items():
                if nums:
                    # 수동 체크 기반으로 완료/미완료 판단
                    actually_missing = []
                    completed = []
                    
                    for num in nums:
                        if is_manually_checked(year, subject, num, manual_check_status):
                            completed.append(num)
                        else:
                            actually_missing.append(num)
                    
                    year_total_missing += len(actually_missing)
                    year_total_completed += len(completed)
            
            # 진행률 계산
            year_total = year_total_missing + year_total_completed
            completion_rate = (year_total_completed / year_total * 100) if year_total > 0 else 0
            
            # 색상 코드로 진행률 표시
            if completion_rate == 100:
                status_emoji = "✅"
                status_color = "green"
            elif completion_rate >= 50:
                status_emoji = "🟡"
                status_color = "orange"
            else:
                status_emoji = "🔴"
                status_color = "red"
            
            with st.expander(f"{status_emoji} {year}년 - 완료율: {completion_rate:.1f}% ({year_total_completed}/{year_total}) | {len(missing_data[year])}개 과목"):
                for subject, nums in missing_data[year].items():
                    if nums:
                        # 수동 체크 기반으로 완료/미완료 판단
                        actually_missing = []
                        completed = []
                        
                        for num in nums:
                            if is_manually_checked(year, subject, num, manual_check_status):
                                completed.append(num)
                            else:
                                actually_missing.append(num)
                        
                        # 과목별 진행률
                        subject_total = len(nums)
                        subject_completion_rate = (len(completed) / subject_total * 100) if subject_total > 0 else 0
                        
                        if subject_completion_rate == 100:
                            subject_status = "✅"
                        elif subject_completion_rate > 0:
                            subject_status = "🟡"
                        else:
                            subject_status = "🔴"
                        
                        st.markdown(f"{subject_status} **{subject}**: {subject_completion_rate:.0f}% 완료 ({len(completed)}/{subject_total})")
                        
                        # 미완료 문항 표시 (빨간색)
                        if actually_missing:
                            ranges = []
                            start = actually_missing[0]
                            end = start
                            
                            for i in range(1, len(actually_missing)):
                                if actually_missing[i] == end + 1:
                                    end = actually_missing[i]
                                else:
                                    ranges.append(f"{start}~{end}" if start != end else str(start))
                                    start = actually_missing[i]
                                    end = start
                            
                            ranges.append(f"{start}~{end}" if start != end else str(start))
                            
                            st.markdown(f'  <span style="color:red">❌ 미완료: {", ".join(ranges)}번</span>', unsafe_allow_html=True)
                        
                        # 완료 문항 표시 (초록색)
                        if completed:
                            ranges = []
                            start = completed[0]
                            end = start
                            
                            for i in range(1, len(completed)):
                                if completed[i] == end + 1:
                                    end = completed[i]
                                else:
                                    ranges.append(f"{start}~{end}" if start != end else str(start))
                                    start = completed[i]
                                    end = start
                            
                            ranges.append(f"{start}~{end}" if start != end else str(start))
                            
                            st.markdown(f'  <span style="color:green">✅ 완료됨: {", ".join(ranges)}번</span>', unsafe_allow_html=True)
                        
                        st.markdown("---")
    else:
        st.info("파싱된 누락 문항 데이터가 없습니다.")

# ==========================================
# 🔧 관리자 도구
# ==========================================
st.markdown("---")
with st.expander("🔧 관리자 도구"):
    col_tools1, col_tools2, col_tools3 = st.columns(3)
    
    with col_tools1:
        st.subheader("📦 백업 관리")
        
        # 백업 파일 목록
        if os.path.exists(BACKUP_DIR):
            backup_files = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_*.jsonl")), reverse=True)
            
            if backup_files:
                st.info(f"총 {len(backup_files)}개의 백업 파일이 있습니다.")
                
                # 최근 5개만 표시
                for backup_file in backup_files[:5]:
                    filename = os.path.basename(backup_file)
                    file_size = os.path.getsize(backup_file)
                    file_time = datetime.fromtimestamp(os.path.getmtime(backup_file))
                    
                    st.text(f"📄 {filename}")
                    st.caption(f"   크기: {file_size:,} bytes | 시간: {file_time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                st.info("백업 파일이 없습니다.")
        
        # 수동 백업 버튼
        if st.button("지금 백업 생성", key="manual_backup"):
            success, msg = create_backup()
            if success:
                st.success(f"백업 생성 완료: {os.path.basename(msg)}")
            else:
                st.error(msg)
    
    with col_tools2:
        st.subheader("✅ 데이터 검증")
        
        if st.button("전체 데이터 검증", key="validate_all"):
            invalid_count = 0
            invalid_items = []
            
            with st.spinner("데이터 검증 중..."):
                for idx, entry in enumerate(st.session_state['data']):
                    is_valid, msg = validate_entry(entry)
                    if not is_valid:
                        invalid_count += 1
                        invalid_items.append({
                            'index': idx,
                            'id': entry.get('unique_id', 'N/A'),
                            'error': msg
                        })
            
            if invalid_count == 0:
                st.success(f"✅ 모든 데이터가 유효합니다! (총 {len(st.session_state['data'])}개)")
            else:
                st.error(f"❌ {invalid_count}개의 유효하지 않은 데이터가 발견되었습니다.")
                
                # 오류 상세 표시
                df = pd.DataFrame(invalid_items)
                st.dataframe(df, use_container_width=True)
        
        # 중복 ID 체크
        if st.button("중복 ID 검사", key="check_duplicates"):
            id_counts = {}
            for entry in st.session_state['data']:
                uid = entry.get('unique_id', 'N/A')
                id_counts[uid] = id_counts.get(uid, 0) + 1
            
            duplicates = {k: v for k, v in id_counts.items() if v > 1}
            
            if not duplicates:
                st.success("✅ 중복된 ID가 없습니다.")
            else:
                st.error(f"❌ {len(duplicates)}개의 중복 ID가 발견되었습니다:")
                for uid, count in duplicates.items():
                    st.warning(f"  - {uid}: {count}회")
        
        st.markdown("---")
        
        # 데이터 정렬
        if st.button("🔄 데이터 정렬 후 저장", key="sort_data"):
            with st.spinner("데이터 정렬 중..."):
                if save_data_to_file(st.session_state['data']):
                    st.success("✅ 데이터가 정렬되어 저장되었습니다!")
                    st.info("정렬 순서: 연도 → 과목 → 문항번호")
                    st.rerun()
                else:
                    st.error("❌ 데이터 저장 실패")
    
    with col_tools3:
        st.subheader("📁 PDF 디렉토리 진단")
        
        if st.button("PDF 경로 확인", key="check_pdf_dir"):
            st.text(f"설정된 경로:\n{PDF_ARCHIVE_DIR}")
            
            if os.path.exists(PDF_ARCHIVE_DIR):
                st.success("✅ 디렉토리 존재")
                
                # 연도 폴더 목록
                year_folders = sorted([d for d in os.listdir(PDF_ARCHIVE_DIR) 
                                     if os.path.isdir(os.path.join(PDF_ARCHIVE_DIR, d))])
                
                st.info(f"발견된 연도 폴더: {len(year_folders)}개")
                
                # 처음 5개만 표시
                for folder in year_folders[:5]:
                    st.text(f"  📁 {folder}")
                    
                    # PDF 파일 수 확인
                    folder_path = os.path.join(PDF_ARCHIVE_DIR, folder)
                    pdf_files = glob.glob(os.path.join(folder_path, "*.pdf"))
                    st.caption(f"     → PDF 파일: {len(pdf_files)}개")
                
                if len(year_folders) > 5:
                    st.caption(f"... 외 {len(year_folders) - 5}개 폴더")
            else:
                st.error(f"❌ 디렉토리가 존재하지 않습니다.")
                st.info("다음 경로 중 하나를 사용하세요:\n- data/raw_pdfs\n- data/archive")
        
        # 현재 선택된 연도/과목의 PDF 검색
        if st.button("현재 선택 PDF 찾기", key="find_current_pdf"):
            pdf_path, msg = find_pdf_path(selected_year, selected_subject)
            
            if pdf_path and msg == "Success":
                st.success(f"✅ 찾음!")
                st.text(os.path.basename(pdf_path))
                st.caption(f"전체 경로:\n{pdf_path}")
            else:
                st.error("❌ 찾을 수 없음")
                st.text(msg)

# ==========================================
# 📊 Footer 정보
# ==========================================
st.markdown("---")
st.caption(f"💾 데이터 파일: `{DATA_FILE}` | 📁 PDF 경로: `{PDF_ARCHIVE_DIR}` | 🔄 백업 경로: `{BACKUP_DIR}`")
