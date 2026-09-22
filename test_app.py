import unittest

import app


class EmailParserTests(unittest.TestCase):
    def test_parse_email_extracts_listings_from_html(self):
        raw_email = """
From: listings@example.com
Subject: New Ottawa listings
MIME-Version: 1.0
Content-Type: text/html; charset=UTF-8

<html>
  <body>
    <div class="listing-card">
      <a href="https://example.com/listings/ott-100">124 Maple Grove Crescent</a>
      <div>Ottawa, ON</div>
      <div>$529,900</div>
      <div>3 bed · 2 bath · Detached</div>
    </div>
    <div class="listing-card">
      <a href="https://example.com/listings/ott-101">48 Riverside Avenue</a>
      <div>Ottawa, ON</div>
      <div>$549,000</div>
      <div>4 bed · 2.5 bath · Detached</div>
    </div>
  </body>
</html>
"""

        listings = app.extract_listings_from_email(raw_email)

        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0]["address"], "124 Maple Grove Crescent")
        self.assertEqual(listings[0]["price"], 529900)
        self.assertEqual(listings[0]["property_type"], "Detached")
        self.assertEqual(listings[1]["url"], "https://example.com/listings/ott-101")


if __name__ == "__main__":
    unittest.main()
