import asyncio
import re

import aiofiles
import httpx
from bs4.element import PageElement
from markdownify import MarkdownConverter

URL_ROOT = "https://www.gov.uk/guidance/the-highway-code/"


class CustomMarkdownConverter(MarkdownConverter):
    def convert_figcaption(self, el: PageElement, text: str, convert_as_inline: bool):
        """The library doesn't handle this element for some reason"""
        return "%s\n\n\n" % text if text else ""

    def convert_img(self, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """This fixes https://github.com/matthewwithanm/python-markdownify/issues/61"""
        alt = el.attrs.get("alt", None) or ""
        src = el.attrs.get("src", None) or ""
        title = el.attrs.get("title", None) or ""
        title_part = ' "%s"' % title.replace('"', r"\"") if title else ""

        return "![%s](%s%s)" % (alt, src, title_part)

    def convert_tr(self, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """I have to override this to handle tables that don't have headers"""
        cells = el.find_all(["td", "th"])
        overline = ""
        underline = ""

        if not el.previous_sibling and el.parent.name in ["table", "tbody"]:
            if (
                not el.parent.previous_sibling
                or el.parent.previous_sibling.name != "thead"
            ):
                overline += "|" + "|" * len(cells) + "\n"
            overline += "| " + " | ".join(["---"] * len(cells)) + " |" + "\n"

        return overline + "|" + text + "\n" + underline


def clean_markdown(markdown: str) -> str:
    # Trailing whitespace
    cleaned = re.sub(r" +\n", "\n", markdown)

    # Excess line breaks
    cleaned = cleaned.replace("\n" * 20, "\n\n")
    for i in range(19, 2, -1):
        cleaned = cleaned.replace("\n" * i, "\n\n")

    # Unicode characters that Github won't render
    bad_characters = ["\u2028"]
    for character in bad_characters:
        cleaned = cleaned.replace(character, "")

    cleaned = cleaned.strip()
    cleaned += "\n"

    return cleaned


def rewrite_urls(markdown: str) -> str:
    url_pattern = re.compile(
        r"\((?P<unneeded>[https://www\.gov\.uk]?/guidance/the-highway-code/)(?P<filename>[^#)]*)(?P<fragment>#[^)]*)?\)"
    )

    matches = re.findall(url_pattern, markdown)
    for match in matches:
        str_to_replace = "".join(match)
        _, filename, fragment = match
        replacement = f"/pages/{filename}.md{fragment}"
        markdown = markdown.replace(str_to_replace, replacement)

    # Not a fix for all fragments/anchors, but catches the majority
    markdown = markdown.replace("#rule", "#rule-")

    return markdown


async def save_images(markdown: str, client: httpx.AsyncClient) -> str:
    valid_file_extensions = [
        ".apng",
        ".avif",
        ".gif",
        ".jpg",
        ".jpeg",
        ".jfif",
        ".pjpeg",
        ".pjp",
        ".png",
        ".svg",
        ".webp",
    ]
    image_pattern = re.compile(
        fr'\((?P<url_root>[^)]*/)(?P<filename>[^.]*)(?P<extension>{"|".join(valid_file_extensions)})\)'
    )

    matches = re.findall(image_pattern, markdown)
    for match in matches:
        old_path = "".join(match)
        new_path = f"images/{match[1]}{match[2]}"

        async with aiofiles.open(new_path, "wb") as fh:
            async with client.stream(
                "GET", old_path, follow_redirects=True
            ) as response:
                async for chunk in response.aiter_bytes():
                    await fh.write(chunk)

        markdown = markdown.replace(old_path, "../" + new_path)

    return markdown


async def process_page(filename: str, client: httpx.AsyncClient):
    response = await client.get(URL_ROOT + filename, follow_redirects=True)
    response.raise_for_status()
    print(filename)

    converter = CustomMarkdownConverter()

    async with aiofiles.open(f"pages/{filename}.md", "w") as fh:
        page_pattern = r"<article(.*)>([\S\s]*)</article>"
        sub_page = re.search(page_pattern, response.text)

        if sub_page and sub_page.groups():
            markdown = converter.convert(sub_page.groups()[1])
            cleaned_markdown = clean_markdown(markdown)
            rewritten = rewrite_urls(cleaned_markdown)
            with_local_images = await save_images(rewritten, client)
            await fh.write(with_local_images)


async def create_and_update_pages(client: httpx.AsyncClient):
    page = await client.get(URL_ROOT, follow_redirects=True)
    sections_pattern = r"\"\/guidance\/the-highway-code\/(.*)\""
    sections = re.findall(sections_pattern, page.text)

    await asyncio.gather(*[process_page(section, client) for section in sections])


async def main():
    async with httpx.AsyncClient() as client:
        await create_and_update_pages(client)


def markdown_printer(index: int) -> None:
    """Helper function for quick local testing of markdown changes. `index` is the index of the
    desired section of the Highway Code (`sections`) you want to print"""
    page = httpx.get(URL_ROOT, follow_redirects=True)
    sections_pattern = r"\"\/guidance\/the-highway-code\/(.*)\""
    # [
    # 'updates',
    # 'introduction',
    # 'rules-for-pedestrians-1-to-35',
    # 'rules-for-users-of-powered-wheelchairs-and-mobility-scooters-36-to-46',
    # 'rules-about-animals-47-to-58',
    # 'rules-for-cyclists-59-to-82',
    # 'rules-for-motorcyclists-83-to-88',
    # 'rules-for-drivers-and-motorcyclists-89-to-102',
    # 'general-rules-techniques-and-advice-for-all-drivers-and-riders-103-to-158',
    # 'using-the-road-159-to-203',
    # 'road-users-requiring-extra-care-204-to-225',
    # 'driving-in-adverse-weather-conditions-226-to-237',
    # 'waiting-and-parking-238-to-252',
    # 'motorways-253-to-273',
    # 'breakdowns-and-incidents-274-to-287',
    # 'road-works-level-crossings-and-tramways-288-to-307',
    # 'light-signals-controlling-traffic',
    # 'signals-to-other-road-users',
    # 'signals-by-authorised-persons',
    # 'traffic-signs',
    # 'road-markings',
    # 'vehicle-markings',
    # 'annex-1-you-and-your-bicycle',
    # 'annex-2-motorcycle-licence-requirements',
    # 'annex-3-motor-vehicle-documentation-and-learner-driver-requirements',
    # 'annex-4-the-road-user-and-the-law',
    # 'annex-5-penalties',
    # 'annex-6-vehicle-maintenance-safety-and-security',
    # 'annex-7-first-aid-on-the-road',
    # 'annex-8-safety-code-for-new-drivers',
    # 'other-information',
    # 'index'
    # ]
    sections = re.findall(sections_pattern, page.text)
    filename = sections[index]

    page_pattern = r"<article(.*)>([\S\s]*)</article>"
    response = httpx.get(URL_ROOT + filename, follow_redirects=True)

    converter = CustomMarkdownConverter()

    if sub_page := re.search(page_pattern, response.text):
        print(converter.convert(sub_page.groups()[1]))


if __name__ == "__main__":
    asyncio.run(main())
