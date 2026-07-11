import os


os.environ["TESTING"] = "true"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_URL_HOST", None)
