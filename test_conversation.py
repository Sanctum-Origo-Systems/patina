from patina.conversations import build_checkpoint_summary, get_recent_messages, store_exchange
from patina.store import connect, get_db_path, init_db

db = get_db_path()
init_db(db)
conn = connect(db)

store_exchange(conn, "test", "andy", "user", "hello")
store_exchange(conn, "test", "andy", "assistant", "good morning")
store_exchange(conn, "test", "andy", "user", "what needs my attention?")

print(get_recent_messages(conn, "test", limit=5))
print(build_checkpoint_summary(conn, "test"))
