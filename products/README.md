# Your product list goes here

Put `products.csv` (or `products.xlsx`) in this folder **only in a private copy** of the repository.
Never commit a real product list to a public repository.

Columns are recognised by name (English, Turkish and Odoo export headers):

| Column | Examples of accepted headers |
|---|---|
| Product name | `Name`, `Product`, `Ürün Adı` |
| Brand (optional) | `Brand`, `Marka`. Without it, the part of the name before the first comma is used. |
| Unit barcode | `Barcode`, `UPC`, `EAN`, `GTIN`, `Barkod` |
| Case barcode (optional) | `Box Barcode`, `Case Barcode`, `ITF14`, `Koli Barkodu` |
| Your code (optional) | `Internal Reference`, `SKU`, `Stok Kodu` |

`ignore-brands.txt` lists brand names that are ordinary words and would match unrelated recalls.
