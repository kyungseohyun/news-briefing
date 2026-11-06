"""settings.json 에 적힌 RSS 주소에서 최신 글을 가져와 JSON 으로 보여 주는 프로그램.

실행 방법 (이 파일이 있는 폴더에서):
    python fetch_latest.py

RSS 란? 언론사가 새 글 목록을 XML 이라는 형식으로 공개해 둔 주소입니다.
이 프로그램은 그 XML 을 내려받아 필요한 정보만 골라냅니다.
"""

# import 는 "이 도구를 쓰겠다"는 선언입니다.
# 아래는 모두 Python 에 처음부터 들어 있어서 따로 설치할 필요가 없습니다.
import json  # JSON 읽기와 쓰기
import sys  # 화면 출력 설정
import urllib.request  # 인터넷 주소에서 내용 내려받기
import xml.etree.ElementTree as ET  # XML 해석하기 (ET 라는 짧은 이름으로 부릅니다)
from datetime import datetime, timedelta, timezone  # 날짜와 시간 다루기
from pathlib import Path  # 파일 경로 다루기

# 대문자 이름은 "프로그램 안에서 바뀌지 않는 값"이라는 관례입니다.
# 가져올 글 수를 바꾸고 싶으면 LATEST_COUNT 의 숫자만 고치면 됩니다.
LATEST_COUNT = 3  # 언론사별로 가져올 글 수
TIMEOUT_SECONDS = 30  # 서버가 이 시간 안에 답하지 않으면 포기합니다

# __file__ 은 이 파일의 위치입니다. 어디서 실행해도 같은 폴더의 설정을 찾게 해 줍니다.
SETTINGS_PATH = Path(__file__).parent / "settings.json"

# 한국 시간(UTC+9)입니다.
KOREA_TIME = timezone(timedelta(hours=9))

# 언론사마다 날짜를 적는 방식이 달라서 두 가지 형식을 모두 준비합니다.
DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",  # 예: 2026-11-06 20:16:21 (이코노믹 리뷰)
    "%a, %d %b %Y %H:%M:%S %z",  # 예: Fri, 06 Nov 2026 20:25:55 +09:00 (매일경제)
]

# 날짜를 읽지 못한 글을 정렬할 때 쓰는 "아주 오래된 날짜"입니다.
# 이 값 덕분에 그런 글은 목록의 맨 뒤로 갑니다.
OLDEST_DATE = datetime(1900, 1, 1, tzinfo=KOREA_TIME)


def load_settings():
    """settings.json 파일을 읽어서 Python 데이터로 돌려줍니다."""
    # encoding="utf-8" 은 한글이 깨지지 않게 읽으라는 뜻입니다.
    with open(SETTINGS_PATH, encoding="utf-8") as file:
        return json.load(file)


def download(url):
    """주소의 내용을 내려받아 돌려줍니다."""
    # User-Agent 는 "나는 어떤 프로그램입니다"라고 서버에 밝히는 이름표입니다.
    # 이름표가 없으면 요청을 거절하는 사이트가 있어서 넣어 줍니다.
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (news-briefing)"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def parse_date(text):
    """날짜 글자를 날짜 데이터로 바꿉니다. 읽지 못하면 None(값 없음)을 돌려줍니다."""
    # 준비한 형식을 하나씩 대입해 보고, 맞는 형식을 찾으면 바로 끝냅니다.
    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)
        except ValueError:
            continue  # 이 형식이 아니면 다음 형식을 시도합니다

        # 시간대가 안 적힌 날짜는 한국 시간으로 간주합니다.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KOREA_TIME)
        return parsed

    return None  # 어떤 형식에도 맞지 않는 경우


def get_sort_date(article):
    """정렬에 쓸 날짜를 돌려줍니다. 날짜가 없는 글은 가장 오래된 글로 칩니다."""
    return article["parsed_date"] or OLDEST_DATE


def format_date(article):
    """글의 날짜를 화면에 보여 줄 글자로 바꿉니다."""
    parsed_date = article["parsed_date"]
    if parsed_date:
        # 두 언론사의 날짜를 같은 모양의 한국 시간으로 맞춥니다.
        return parsed_date.astimezone(KOREA_TIME).strftime("%Y-%m-%d %H:%M:%S")
    return article["date_text"]  # 읽지 못한 날짜는 원래 글자 그대로 둡니다


def read_articles(xml_data):
    """RSS(XML) 내용에서 글 목록을 뽑아냅니다."""
    root = ET.fromstring(xml_data)  # XML 글자를 다루기 쉬운 나무 구조로 바꿉니다

    articles = []  # 글을 하나씩 담을 빈 목록
    # RSS 에서는 글 하나가 <item> 태그 하나입니다. ".//item" 은 "모든 item"이라는 뜻입니다.
    for item in root.findall(".//item"):
        # findtext("title", "") 는 <title> 안의 글자를 꺼내고, 없으면 빈 글자를 줍니다.
        # strip() 은 앞뒤의 공백과 줄바꿈을 지웁니다.
        date_text = item.findtext("pubDate", "").strip()
        articles.append(
            {
                "title": item.findtext("title", "").strip(),
                "link": item.findtext("link", "").strip(),
                "description": item.findtext("description", "").strip(),
                "date_text": date_text,
                "parsed_date": parse_date(date_text),
            }
        )
    return articles


def pick_latest(articles, count):
    """글을 최신순으로 정렬해 앞에서 count 개만 골라 화면용으로 정리합니다."""
    # reverse=True 는 큰 값(최근 날짜)이 앞으로 오게 합니다.
    newest_first = sorted(articles, key=get_sort_date, reverse=True)

    result = []
    # [:count] 는 목록의 앞에서 count 개만 잘라 냅니다.
    for article in newest_first[:count]:
        # 요청한 세 가지 정보만 남깁니다.
        result.append(
            {
                "title": article["title"],
                "link": article["link"],
                "date": format_date(article),
            }
        )
    return result


def main():
    """프로그램의 전체 순서입니다."""
    # Windows 화면에서 한글이 깨지지 않도록 출력 방식을 UTF-8 로 맞춥니다.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    settings = load_settings()

    output = {}  # 언론사 이름별로 결과를 담을 빈 묶음
    for feed in settings["feeds"]:
        # try 안에서 문제가 생기면 except 로 넘어갑니다.
        # 한 언론사가 실패해도 나머지 언론사는 계속 가져오기 위해서입니다.
        try:
            xml_data = download(feed["url"])
            articles = read_articles(xml_data)
        except Exception as error:
            print(f"{feed['name']} 가져오기 실패: {error}", file=sys.stderr)
            continue

        output[feed["name"]] = pick_latest(articles, LATEST_COUNT)

    # ensure_ascii=False 는 한글을 그대로 보여 주고, indent=2 는 보기 좋게 들여 씁니다.
    print(json.dumps(output, ensure_ascii=False, indent=2))


# 이 파일을 직접 실행했을 때만 main() 을 시작하라는 Python 의 관용구입니다.
if __name__ == "__main__":
    main()
