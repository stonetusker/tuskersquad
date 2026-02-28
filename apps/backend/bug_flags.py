import os


BUG_PRICE=os.getenv("BUG_PRICE","false").lower()=="true"

BUG_SECURITY=os.getenv("BUG_SECURITY","false").lower()=="true"

BUG_SLOW=os.getenv("BUG_SLOW","false").lower()=="true"
