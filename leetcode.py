# -*- coding: utf-8 -*-
import logging
import datetime
import requests

logger = logging.getLogger(__name__)

GRAPHQL_QUERY = (
    "query questionOfToday { activeDailyCodingChallengeQuestion {"
    " date userStatus link question {"
    " acRate difficulty freqBar frontendQuestionId: questionFrontendId"
    " isFavor paidOnly: isPaidOnly status title titleSlug"
    " hasVideoSolution hasSolution topicTags { name id slug } } } }"
)

_last_link = ""


def get_result():
    url = "https://leetcode.com/graphql/"
    return requests.get(url, params={"query": GRAPHQL_QUERY})


def get_link():
    return _last_link


def main():
    global _last_link

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
    for c in get_upcoming_contests():
        print(f"{c['title']} - {c['start']}")
