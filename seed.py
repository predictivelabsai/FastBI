"""Build the synthetic FastBI warehouse + saved queries/charts/dashboards.

Deterministic, no PII. Creates a small retail sales star schema (wh_*) and the
app metadata that explores it.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import db

RNG = random.Random(20260611)
START = date(2024, 1, 1)
END = date(2026, 5, 31)

REGIONS = ["UK", "DACH", "Nordics", "Iberia", "Benelux", "North America", "APAC"]
CATEGORIES = ["Apparel", "Electronics", "Home", "Beauty", "Sports", "Grocery"]
CHANNELS = ["Online", "Retail", "Wholesale", "Partner"]
PROD_ADJ = ["Pro", "Lite", "Max", "Eco", "Prime", "Go", "Plus", "Air", "Neo", "Core"]


def _build_warehouse():
    with db.cursor() as conn:
        conn.executescript("""
        DROP TABLE IF EXISTS wh_orders;
        DROP TABLE IF EXISTS wh_customers;
        DROP TABLE IF EXISTS wh_products;
        DROP TABLE IF EXISTS wh_regions;
        CREATE TABLE wh_regions (region_id INTEGER PRIMARY KEY, region TEXT, country TEXT);
        CREATE TABLE wh_products (product_id INTEGER PRIMARY KEY, product TEXT, category TEXT, unit_price REAL);
        CREATE TABLE wh_customers (customer_id INTEGER PRIMARY KEY, customer TEXT, region_id INTEGER, segment TEXT, signup_date TEXT);
        CREATE TABLE wh_orders (order_id INTEGER PRIMARY KEY, order_date TEXT, customer_id INTEGER,
            product_id INTEGER, channel TEXT, quantity INTEGER, revenue REAL, cost REAL, discount REAL);
        """)
        # regions
        conn.executemany("INSERT INTO wh_regions(region,country) VALUES (?,?)",
                         [(r, r) for r in REGIONS])
        region_ids = [r[0] for r in conn.execute("SELECT region_id FROM wh_regions").fetchall()]
        # products
        products = []
        for cat in CATEGORIES:
            for _ in range(6):
                name = f"{cat[:4]}-{RNG.choice(PROD_ADJ)}{RNG.randint(10,99)}"
                products.append((name, cat, round(RNG.uniform(8, 480), 2)))
        conn.executemany("INSERT INTO wh_products(product,category,unit_price) VALUES (?,?,?)", products)
        prod_rows = conn.execute("SELECT product_id,unit_price FROM wh_products").fetchall()
        # customers
        customers = []
        for i in range(220):
            customers.append((f"Customer {i+1:03d}", RNG.choice(region_ids),
                              RNG.choice(["SMB", "Mid-Market", "Enterprise", "Consumer"]),
                              (START + timedelta(days=RNG.randint(0, 700))).isoformat()))
        conn.executemany(
            "INSERT INTO wh_customers(customer,region_id,segment,signup_date) VALUES (?,?,?,?)", customers)
        cust_ids = [r[0] for r in conn.execute("SELECT customer_id FROM wh_customers").fetchall()]
        # orders — seasonal-ish growth
        orders = []
        days = (END - START).days
        for _ in range(4200):
            d = START + timedelta(days=RNG.randint(0, days))
            # mild upward trend + Q4 bump
            month = d.month
            season = 1.35 if month in (11, 12) else (0.85 if month in (1, 2) else 1.0)
            trend = 1 + ((d - START).days / days) * 0.6
            pr = RNG.choice(prod_rows)
            qty = RNG.randint(1, 12)
            base = pr["unit_price"] * qty
            disc = round(base * RNG.choice([0, 0, 0, 0.05, 0.1, 0.15]), 2)
            revenue = round(base * season * trend - disc, 2)
            cost = round(base * RNG.uniform(0.45, 0.7), 2)
            orders.append((d.isoformat(), RNG.choice(cust_ids), pr["product_id"],
                           RNG.choice(CHANNELS), qty, revenue, cost, disc))
        conn.executemany(
            """INSERT INTO wh_orders(order_date,customer_id,product_id,channel,quantity,revenue,cost,discount)
               VALUES (?,?,?,?,?,?,?,?)""", orders)
    return len(orders)


QUERIES = [
    ("Monthly revenue", "Total revenue by month", "line", "month", "revenue", """
SELECT substr(order_date,1,7) AS month, ROUND(SUM(revenue),0) AS revenue
FROM wh_orders GROUP BY month ORDER BY month"""),
    ("Revenue by region", "Revenue split across regions", "bar", "region", "revenue", """
SELECT r.region, ROUND(SUM(o.revenue),0) AS revenue
FROM wh_orders o JOIN wh_customers c ON c.customer_id=o.customer_id
JOIN wh_regions r ON r.region_id=c.region_id
GROUP BY r.region ORDER BY revenue DESC"""),
    ("Revenue by category", "Which categories sell most", "pie", "category", "revenue", """
SELECT p.category, ROUND(SUM(o.revenue),0) AS revenue
FROM wh_orders o JOIN wh_products p ON p.product_id=o.product_id
GROUP BY p.category ORDER BY revenue DESC"""),
    ("Top 10 customers", "Highest-spending customers", "bar", "customer", "revenue", """
SELECT c.customer, ROUND(SUM(o.revenue),0) AS revenue
FROM wh_orders o JOIN wh_customers c ON c.customer_id=o.customer_id
GROUP BY c.customer ORDER BY revenue DESC LIMIT 10"""),
    ("Orders by channel", "Order volume per channel", "bar", "channel", "orders", """
SELECT channel, COUNT(*) AS orders FROM wh_orders GROUP BY channel ORDER BY orders DESC"""),
    ("Gross margin by month", "Revenue minus cost over time", "line", "month", "margin", """
SELECT substr(order_date,1,7) AS month, ROUND(SUM(revenue-cost),0) AS margin
FROM wh_orders GROUP BY month ORDER BY month"""),
    ("Avg order value by segment", "AOV across customer segments", "bar", "segment", "aov", """
SELECT c.segment, ROUND(AVG(o.revenue),2) AS aov
FROM wh_orders o JOIN wh_customers c ON c.customer_id=o.customer_id
GROUP BY c.segment ORDER BY aov DESC"""),
]

DASHBOARDS = [
    ("Revenue Overview", "Headline revenue, margin and mix",
     [("Monthly revenue", "full"), ("Revenue by region", "half"),
      ("Revenue by category", "half"), ("Gross margin by month", "full")]),
    ("Customers & Channels", "Who buys, and how",
     [("Top 10 customers", "full"), ("Orders by channel", "half"),
      ("Avg order value by segment", "half")]),
]


def build():
    n_orders = _build_warehouse()
    db.init_app_schema()
    with db.cursor() as conn:
        for t in ("dashboard_charts", "charts", "dashboards", "queries", "chat_messages"):
            conn.execute(f"DELETE FROM {t}")
        qid_by_title, cid_by_qtitle = {}, {}
        for title, desc, ctype, x, y, sql in QUERIES:
            conn.execute("INSERT INTO queries(title,description,sql,folder) VALUES (?,?,?,?)",
                         (title, desc, sql.strip(), "Sales"))
            qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            qid_by_title[title] = qid
            conn.execute("INSERT INTO charts(title,query_id,chart_type,x_col,y_col) VALUES (?,?,?,?,?)",
                         (title, qid, ctype, x, y))
            cid_by_qtitle[title] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for title, desc, items in DASHBOARDS:
            conn.execute("INSERT INTO dashboards(title,description) VALUES (?,?)", (title, desc))
            did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for pos, (qtitle, width) in enumerate(items):
                conn.execute(
                    "INSERT INTO dashboard_charts(dashboard_id,chart_id,position,width) VALUES (?,?,?,?)",
                    (did, cid_by_qtitle[qtitle], pos, width))

    print(f"FastBI seeded → {db.DB_PATH}")
    print(f"  warehouse: {n_orders} orders · {len(QUERIES)} queries/charts · {len(DASHBOARDS)} dashboards")


if __name__ == "__main__":
    build()
