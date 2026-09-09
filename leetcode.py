# -*- coding: utf-8 -*-
import logging
import datetime
import requests
from bs4 import BeautifulSoup, NavigableString

logger = logging.getLogger(__name__)

GRAPHQL_QUERY = (
    "query questionOfToday { activeDailyCodingChallengeQuestion {"
    " date userStatus link question {"
    " acRate difficulty freqBar frontendQuestionId: questionFrontendId"
    " isFavor paidOnly: isPaidOnly status title titleSlug content"
    " hasVideoSolution hasSolution topicTags { name id slug } } } }"
)

_last_link = ""
_last_description = ""


def get_result():
    url = "https://leetcode.com/graphql/"
    return requests.get(url, params={"query": GRAPHQL_QUERY})


def get_link():
    return _last_link


def get_description():
    return _last_description


def _html_to_markdown(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    def walk(node, in_pre=False):
        if isinstance(node, NavigableString):
            return str(node)
        name = (node.name or "").lower()
        next_pre = in_pre or name == "pre"
        children = "".join(walk(c, next_pre) for c in node.children)
        if in_pre:
            return children
        if name in ("p", "div"):
            return children + "\n\n"
        if name == "br":
            return "\n"
        if name in ("strong", "b"):
            return f"**{children}**"
        if name in ("em", "i"):
            return f"*{children}*"
        if name == "code":
            return f"`{children}`"
        if name == "pre":
            return f"```\n{children.strip()}\n```\n\n"
        if name in ("ul", "ol"):
            return children + "\n"
        if name == "li":
            return f"- {children.strip()}\n"
        if name == "sup":
            return f"^{children}"
        if name == "sub":
            return f"_{children}"
        return children

    text = walk(soup)
    text = text.replace("\u00a0", " ")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def main():
    global _last_link, _last_description

    now = datetime.datetime.now()
    result = get_result()
    j = result.json()

    try:
        question = j["data"]["activeDailyCodingChallengeQuestion"]["question"]
    except (KeyError, TypeError) as e:
        logger.error("LeetCode API 回傳格式異常: %s", e)
        return "出現錯誤QQ"

    title = question["title"]
    qid = question["frontendQuestionId"]
    _last_link = (
        "https://leetcode.com"
        + j["data"]["activeDailyCodingChallengeQuestion"]["link"]
        + f"?envType=daily-question&envId={now.year}-{now.month}-{now.day}"
    )
    _last_description = _html_to_markdown(question.get("content"))

    full_title = f"{qid}. {title}"
    return f"{now.month}/{now.day} {full_title}", question["difficulty"]


CONTEST_QUERY = "query { upcomingContests { title startTime } }"


def get_upcoming_contests():
    url = "https://leetcode.com/graphql/"
    try:
        r = requests.post(url, json={"query": CONTEST_QUERY}, timeout=10)
        data = r.json()["data"]["upcomingContests"]
        contests = []
        for c in data:
            start = datetime.datetime.fromtimestamp(c["startTime"], tz=datetime.timezone.utc)
            contests.append({"title": c["title"], "start": start})
        return contests
    except Exception as e:
        logger.error("取得比賽資訊失敗: %s", e)
        return []


if __name__ == "__main__":
    print(main())
    print(get_link())
    print(get_description())
    for c in get_upcoming_contests():
        print(f"{c['title']} - {c['start']}")
