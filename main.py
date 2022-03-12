import asyncio
import re

import aiofiles
import httpx
from bs4.element import PageElement
from markdownify import MarkdownConverter

URL_ROOT = "https://www.gov.uk/guidance/the-highway-code/"


class CustomMarkdownConverter(MarkdownConverter):
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
            if not el.parent.previous_sibling or el.parent.previous_sibling.name != "thead":
                overline += "|" * len(cells) + "\n"
            overline += "| " + " | ".join(["---"] * len(cells)) + " |" + "\n"

        return overline + "|" + text + "\n" + underline


def clean_markdown(markdown: str) -> str:
    # Trailing whitespace
    cleaned = re.sub(r" +\n", "\n")

    # Excess line breaks
    cleaned = markdown.replace("\n" * 20, "\n\n")
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
    sections = re.findall(sections_pattern, page.text)
    filename = sections[index]

    page_pattern = r"<article(.*)>([\S\s]*)</article>"
    response = httpx.get(URL_ROOT + filename, follow_redirects=True)

    converter = CustomMarkdownConverter()
    sub_page = re.search(page_pattern, response.text)
    markdown = converter.convert(sub_page.groups()[1])

    print(markdown)


if __name__ == "__main__":
    asyncio.run(main())
