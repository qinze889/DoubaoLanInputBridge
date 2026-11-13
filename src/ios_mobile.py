"""Small iOS Safari accommodations for the shared modern phone page.

The layout and visual tokens live in mobile_modern.py for all platforms.
Avoid platform-wide overrides (section, textarea, button), which caused the
Mac-served phone page to fall back to the old design after modern CSS loaded.
"""

STYLE = """
<style id="ios-appearance">
@supports (-webkit-touch-callout: none) {
  textarea, input, select { -webkit-tap-highlight-color: transparent; }
  textarea { font-size: 16px !important; }
}
</style>
"""


def apply(page: str) -> str:
    return page.replace('</head>', STYLE + '</head>', 1)
