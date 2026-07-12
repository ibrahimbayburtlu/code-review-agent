import urllib.request

from agent.review_agent import sh, tool_grep


def fetch_prices(product_ids):
    prices = []
    for pid in product_ids:
        data = urllib.request.urlopen(f"http://api.example.com/price/{pid}").read()
        prices.append(data.decode())
    return prices


def get_orders(db, user_ids):
    orders = []
    for uid in user_ids:
        cur = db.cursor()
        cur.execute("SELECT * FROM orders WHERE user_id = " + str(uid))
        orders.extend(cur.fetchall())
    return orders


def build_report(db, user_ids, product_ids):
    text = ""
    for order in get_orders(db, user_ids):
        text = text + str(order) + "\n"
    for price in fetch_prices(product_ids):
        text = text + price + "\n"
    return text
