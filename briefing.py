"""settings.json 의 모든 RSS 에서 기사를 모아 요약하고 news.json 과 index.html 을 만드는 프로그램.

실행 방법 (이 파일이 있는 폴더에서):
    python briefing.py

기사를 고르는 순서:
    1. 제목이나 소개문에 키워드가 들어간 기사를 최신순으로 먼저 고릅니다.
    2. 그래도 자리가 남으면 나머지 기사를 최신순으로 채웁니다.

기사 본문은 가져오지 않습니다. RSS 목록만 읽고, 기사 페이지는 열지 않습니다.
그래서 Gemini 도 제목과 소개문만 보고 요약합니다.

요약에는 이 폴더의 .env 파일에 적힌 GEMINI_API_KEY 를 씁니다.
키가 없거나 요약에 실패해도 index.html 은 만들어집니다.
"""

import html  # HTML 특수 문자 처리
import json  # JSON 읽기와 쓰기
import re  # 글자 패턴 찾기
import sys  # 화면 출력 설정과 프로그램 종료
import urllib.request  # Gemini 에 요청 보내기
from datetime import datetime  # 현재 시각 구하기
from pathlib import Path  # 파일 경로 다루기

# 같은 폴더의 fetch_latest.py 에 이미 만들어 둔 함수를 가져와서 다시 씁니다.
from fetch_latest import (
    KOREA_TIME,  # 한국 시간대
    TIMEOUT_SECONDS,  # 서버 응답을 기다리는 시간
    download,  # 주소의 내용을 내려받기
    format_date,  # 날짜를 같은 모양의 글자로 바꾸기
    get_sort_date,  # 정렬에 쓸 날짜 구하기
    load_settings,  # settings.json 읽기
    read_articles,  # RSS 에서 기사 목록 뽑기
)

# 찾을 키워드는 settings.json 의 keywords 에서 읽어 옵니다.
MAX_ARTICLES = 5  # news.json 에 담을 최대 기사 수
OUTPUT_PATH = Path(__file__).parent / "news.json"  # 결과를 저장할 파일
HTML_PATH = Path(__file__).parent / "index.html"  # 브리핑 페이지를 저장할 파일
ENV_PATH = Path(__file__).parent / ".env"  # API 키를 적어 두는 파일

PAGE_TITLE = "회계·감사 아침 브리핑"
SUMMARY_LINE_COUNT = 3  # 요약 줄 수

# latest 는 항상 최신 모델을 가리키는 별칭이라, 옛 모델이 없어져도 고칠 필요가 없습니다.
# lite 는 추론 단계 없이 바로 답해서 짧은 요약에 알맞습니다.
GEMINI_MODEL = "gemini-flash-lite-latest"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

SUMMARY_PROMPT = """아래 기사 정보만 보고 한국어로 세 줄 요약을 써 줘.
- 각 줄은 한 문장, 줄 앞에 "- " 를 붙인다
- 기사 정보에 없는 내용, 숫자, 이름은 절대 쓰지 않는다
- 정보가 부족하면 마지막 줄에 "- 자세한 내용은 원문 확인 필요" 라고 쓴다

[기사 정보]
제목: {title}
언론사: {source}
날짜: {date}
소개문: {description}"""

PAGE_STYLE = """
:root { color-scheme: light dark; --bg: #f6f5f1; --card: #ffffff; --text: #1f2328;
        --muted: #646b73; --line: #e1dfd8; --link: #0b5cad; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #16181b; --card: #1f2226; --text: #e8e6e1;
          --muted: #a0a6ad; --line: #33373c; --link: #7db8f0; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.65;
       font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif; }
main { max-width: 720px; margin: 0 auto; padding: 32px 16px; }
h1 { margin: 0; font-size: 1.75rem; line-height: 1.3; }
h2 { margin: 0 0 12px; font-size: 1.15rem; line-height: 1.4; }
.collected { margin: 6px 0 24px; color: var(--muted); font-size: 0.9rem; }
article { margin-bottom: 16px; padding: 20px; background: var(--card);
          border: 1px solid var(--line); border-radius: 10px; }
ul { margin: 0 0 14px; padding-left: 20px; }
.notice { margin: 0 0 14px; color: var(--muted); }
.meta { margin: 0; color: var(--muted); font-size: 0.9rem; }
a { color: var(--link); }
footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--line);
         color: var(--muted); font-size: 0.9rem; }
"""


def collect_articles(feeds):
    """모든 RSS 에서 기사를 모아 하나의 목록으로 돌려줍니다."""
    articles = []
    seen_links = set()  # 이미 담은 기사의 링크를 기억해 두는 곳

    for feed in feeds:
        # 한 언론사가 실패해도 나머지 언론사는 계속 가져옵니다.
        try:
            feed_articles = read_articles(download(feed["url"]))
        except Exception as error:
            print(f"{feed['name']} 가져오기 실패: {error}", file=sys.stderr)
            continue

        for article in feed_articles:
            # 같은 기사가 두 번 들어오면 한 번만 담습니다.
            if article["link"] in seen_links:
                continue
            seen_links.add(article["link"])

            article["source"] = feed["name"]  # 어느 언론사 기사인지 적어 둡니다
            articles.append(article)

    return articles


def find_keywords(article, keywords):
    """기사의 제목이나 소개문에 들어 있는 키워드 목록을 돌려줍니다."""
    text = article["title"] + " " + article["description"]
    # keywords 를 하나씩 살펴보고, text 안에 있는 것만 모아 새 목록을 만듭니다.
    return [keyword for keyword in keywords if keyword in text]


def choose_articles(articles, keywords):
    """키워드 기사를 먼저, 모자라면 최신 기사로 채워 최대 MAX_ARTICLES 개를 고릅니다."""
    newest_first = sorted(articles, key=get_sort_date, reverse=True)

    matched = []  # 키워드가 걸린 기사
    others = []  # 키워드가 걸리지 않은 기사
    for article in newest_first:
        article["keywords"] = find_keywords(article, keywords)
        # 빈 목록은 거짓으로 취급되므로, 키워드가 하나라도 있어야 참이 됩니다.
        if article["keywords"]:
            matched.append(article)
        else:
            others.append(article)

    # 두 목록을 이어 붙이면 키워드 기사가 앞에 옵니다. 그 앞에서 필요한 만큼만 자릅니다.
    return (matched + others)[:MAX_ARTICLES]


def load_api_key():
    """.env 파일에서 GEMINI_API_KEY 를 읽습니다. 없거나 읽지 못하면 빈 글자를 돌려줍니다."""
    # utf-8-sig 는 메모장이 파일 맨 앞에 넣는 보이지 않는 표시까지 처리합니다.
    try:
        text = ENV_PATH.read_text(encoding="utf-8-sig")
    except OSError:  # 파일이 없거나, 같은 이름의 폴더라서 읽을 수 없는 경우
        return ""

    for line in text.splitlines():
        # partition 은 첫 번째 = 를 기준으로 앞과 뒤를 나눕니다.
        name, _, value = line.partition("=")
        if name.strip().upper() == "GEMINI_API_KEY":
            return value.strip().strip("\"'")  # 앞뒤 공백과 따옴표를 지웁니다
    return ""


def clean_text(text):
    """소개문에 섞인 HTML 태그를 지우고 공백을 정리합니다."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return " ".join(text.split())


def summarize(article, api_key):
    """Gemini 로 세 줄 요약을 만들어 줄 목록으로 돌려줍니다. 실패하면 오류를 일으킵니다."""
    prompt = SUMMARY_PROMPT.format(
        title=article["title"],
        source=article["source"],
        date=format_date(article),
        description=clean_text(article["description"]),
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    # 키를 주소가 아닌 헤더에 넣습니다. 오류 메시지에 주소가 찍혀도 키가 보이지 않습니다.
    request = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        result = json.load(response)

    parts = result["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts)

    # "- " 로 시작하는 줄만 요약으로 인정하고, 표시는 페이지에서 다시 붙입니다.
    lines = [line.strip()[2:].strip() for line in text.splitlines()
             if line.strip().startswith("- ")]
    if len(lines) != SUMMARY_LINE_COUNT:
        raise ValueError(f"요약이 {len(lines)}줄로 왔습니다")
    return lines


def add_summaries(chosen, selected):
    """기사마다 요약을 붙입니다. 실패한 기사의 summary 는 빈 목록으로 남깁니다."""
    api_key = load_api_key()
    if not api_key:
        print(".env 에서 GEMINI_API_KEY 를 찾지 못해 요약을 건너뜁니다.", file=sys.stderr)

    for output, article in zip(chosen, selected):
        output["summary"] = []
        if not api_key:
            continue
        # 한 기사가 실패해도 나머지 기사는 계속 요약합니다.
        try:
            output["summary"] = summarize(article, api_key)
        except Exception as error:
            print(f"요약 실패 ({article['title']}): {error}", file=sys.stderr)


def render_article(article):
    """기사 하나를 HTML 조각으로 만듭니다."""
    # 기사 내용을 그대로 넣으면 페이지가 깨질 수 있어 html.escape 로 안전하게 바꿉니다.
    title = html.escape(article["title"])
    source = html.escape(article["source"])

    if article["summary"]:
        items = "".join(f"<li>{html.escape(line)}</li>" for line in article["summary"])
        summary = f"<ul>{items}</ul>"
    else:
        summary = '<p class="notice">요약을 만들지 못했습니다. 원문을 확인해 주세요.</p>'

    # http 로 시작하는 주소만 링크로 만듭니다.
    if article["link"].startswith(("http://", "https://")):
        link = f'<a href="{html.escape(article["link"])}" rel="noopener">원문 보기</a>'
    else:
        link = "원문 링크 없음"

    return f"""<article>
<h2>{title}</h2>
{summary}
<p class="meta">{source} · {link}</p>
</article>"""


def write_page(chosen):
    """브리핑 페이지 index.html 을 저장합니다."""
    collected_at = datetime.now(KOREA_TIME).strftime("%Y-%m-%d %H:%M")

    if chosen:
        body = "\n".join(render_article(article) for article in chosen)
    else:
        body = '<p class="notice">기사를 가져오지 못했습니다.</p>'

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAGE_TITLE}</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
<main>
<h1>{PAGE_TITLE}</h1>
<p class="collected">수집 시각: {collected_at}</p>
{body}
<footer>AI 요약은 틀릴 수 있음</footer>
</main>
</body>
</html>
"""
    HTML_PATH.write_text(page, encoding="utf-8")


def to_output(article):
    """news.json 에 저장할 항목만 골라 정리합니다."""
    return {
        "source": article["source"],
        "title": article["title"],
        "link": article["link"],
        "date": format_date(article),
        "keywords": article["keywords"],  # 빈 목록이면 최신 기사로 채운 것입니다
    }


def main():
    """프로그램의 전체 순서입니다."""
    # Windows 화면에서 한글이 깨지지 않도록 출력 방식을 UTF-8 로 맞춥니다.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    settings = load_settings()
    articles = collect_articles(settings["feeds"])

    # 기사를 하나도 못 가져왔다면 news.json 은 저장하지 않습니다.
    # 빈 결과로 덮어써서 이전 news.json 을 잃지 않기 위해서입니다.
    # 페이지는 그래도 만들어서 실패했다는 사실을 보여 줍니다.
    if not articles:
        write_page([])
        print("가져온 기사가 없어 news.json 을 저장하지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    selected = choose_articles(articles, settings["keywords"])
    chosen = [to_output(article) for article in selected]
    add_summaries(chosen, selected)

    # ensure_ascii=False 는 한글을 그대로 저장하고, indent=2 는 보기 좋게 들여 씁니다.
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(chosen, file, ensure_ascii=False, indent=2)
    write_page(chosen)

    matched_count = sum(1 for article in chosen if article["keywords"])
    summary_count = sum(1 for article in chosen if article["summary"])
    print(f"전체 {len(articles)}개 기사 중 {len(chosen)}개를 {OUTPUT_PATH.name} 에 저장했습니다.")
    print(f"키워드 기사 {matched_count}개, 최신 기사로 채운 기사 {len(chosen) - matched_count}개")
    print(f"요약 {summary_count}개 성공, {HTML_PATH.name} 을 만들었습니다.")


# 이 파일을 직접 실행했을 때만 main() 을 시작하라는 Python 의 관용구입니다.
if __name__ == "__main__":
    main()
