from crawler.html_parser import HTMLParser


def test_parse_valid_html() -> None:
    html = """
    <html>
      <head>
        <title>Test Page</title>
        <meta name="description" content="Test description">
        <meta name="keywords" content="python, crawler">
      </head>
      <body>
        <h1>Main Heading</h1>
        <p>Hello world</p>
        <a href="/about">About</a>
        <img src="/image.jpg" alt="Demo image">
      </body>
    </html>
    """

    parser = HTMLParser()

    result = parser.parse_html(
        html=html,
        url="https://example.com",
    )

    assert result["url"] == "https://example.com"
    assert result["title"] == "Test Page"
    assert "Main Heading" in result["text"]
    assert result["links"] == ["https://example.com/about"]
    assert result["metadata"]["description"] == "Test description"
    assert result["metadata"]["keywords"] == "python, crawler"
    assert result["images"] == [
        {
            "src": "https://example.com/image.jpg",
            "alt": "Demo image",
        }
    ]
    assert result["headings"]["h1"] == ["Main Heading"]
    assert result["parse_errors"] == []


def test_parse_broken_html() -> None:
    html = """
    <html>
      <head>
        <title>Broken Page</title>
      </head>
      <body>
        <h1>Still Works
        <p>Missing closing tags
        <a href="/broken">Broken Link
      </body>
    </html>
    """

    parser = HTMLParser()

    result = parser.parse_html(
        html=html,
        url="https://example.com",
    )

    assert result["title"] == "Broken Page"
    assert "Still Works" in result["text"]
    assert "https://example.com/broken" in result["links"]
    assert isinstance(result["parse_errors"], list)


def test_relative_urls_are_converted_to_absolute() -> None:
    html = """
    <html>
      <body>
        <a href="/about">About</a>
        <a href="contacts">Contacts</a>
        <img src="/logo.png" alt="Logo">
      </body>
    </html>
    """

    parser = HTMLParser()

    result = parser.parse_html(
        html=html,
        url="https://example.com/docs/page",
    )

    assert "https://example.com/about" in result["links"]
    assert "https://example.com/docs/contacts" in result["links"]
    assert result["images"][0]["src"] == "https://example.com/logo.png"


def test_invalid_links_are_filtered() -> None:
    html = """
    <html>
      <body>
        <a href="javascript:void(0)">JS</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="tel:+123456789">Phone</a>
        <a href="#section">Anchor</a>
        <a href="/valid">Valid</a>
      </body>
    </html>
    """

    parser = HTMLParser()

    result = parser.parse_html(
        html=html,
        url="https://example.com",
    )

    assert result["links"] == ["https://example.com/valid"]


def test_same_domain_filtering() -> None:
    html = """
    <html>
      <body>
        <a href="/internal">Internal</a>
        <a href="https://external.com/page">External</a>
      </body>
    </html>
    """

    parser = HTMLParser()

    result = parser.parse_html(
        html=html,
        url="https://example.com",
        same_domain_only=True,
    )

    assert result["links"] == ["https://example.com/internal"]


def test_extract_tables_and_lists() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr>
            <th>Name</th>
            <th>Age</th>
          </tr>
          <tr>
            <td>Alice</td>
            <td>30</td>
          </tr>
        </table>

        <ul>
          <li>First</li>
          <li>Second</li>
        </ul>

        <ol>
          <li>One</li>
          <li>Two</li>
        </ol>
      </body>
    </html>
    """

    parser = HTMLParser()

    result = parser.parse_html(
        html=html,
        url="https://example.com",
    )

    assert result["tables"] == [
        [
            ["Name", "Age"],
            ["Alice", "30"],
        ]
    ]

    assert result["lists"] == [
        {
            "type": "ul",
            "items": ["First", "Second"],
        },
        {
            "type": "ol",
            "items": ["One", "Two"],
        },
    ]


def test_fragment_links_are_stripped() -> None:
    html = """
    <html><body>
        <a href="/page">clean</a>
        <a href="/page#section">fragment</a>
        <a href="/page#other">other-fragment</a>
        <a href="https://external.com/doc#ref">external with fragment</a>
    </body></html>
    """

    parser = HTMLParser()
    result = parser.parse_html(html=html, url="https://example.com")
    links = result["links"]

    assert "https://example.com/page" in links
    assert "https://external.com/doc" in links
    assert not any("#" in link for link in links), "No fragment should survive stripping"
    assert links.count("https://example.com/page") == 1, "Fragment variants must collapse to one URL"
