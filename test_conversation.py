from patina.store import connect, init_db, get_db_path
from patina.conversations import store_exchange, get_recent_messages, build_checkpoint_summary

db = get_db_path()
init_db(db)
conn = connect(db)

store_exchange(conn, 'test', 'andy', 'user', 'hello')
store_exchange(conn, 'test', 'andy', 'assistant', 'good morning')
store_exchange(conn, 'test', 'andy', 'user', 'what needs my attention?')

print(get_recent_messages(conn, 'test', limit=5))
print(build_checkpoint_summary(conn, 'test'))
