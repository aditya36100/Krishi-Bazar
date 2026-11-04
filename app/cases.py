"""Case memory: learns from admin-solved cases (case-based reasoning).
New case -> compare with solved cases (TF-IDF char n-grams + cosine, robust to typos).
Close enough AND the admin allowed auto-apply AND top matches agree -> AUTO resolution.
Otherwise ESCALATE to admin; when the admin resolves it, the case is stored and used next time."""
import sqlite3
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def init(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, text TEXT, resolution TEXT, "
                 "auto_ok INT DEFAULT 0, bad_auto INT DEFAULT 0, created TEXT)")
    conn.commit()

def submit(conn, text, threshold=0.4, k=3):
    rows = conn.execute("SELECT id, text, resolution, auto_ok FROM cases "
                        "WHERE resolution IS NOT NULL AND bad_auto = 0").fetchall()
    best = []
    if rows:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, sublinear_tf=True)
        m = vec.fit_transform([r[1] for r in rows] + [text])
        sims = cosine_similarity(m[-1], m[:-1])[0]
        best = sorted(zip(sims, rows), key=lambda x: -x[0])[:k]
    if best and best[0][0] >= threshold and best[0][1][3] == 1:
        near = [r[2] for s, r in best if s >= threshold]
        if len(set(near)) == 1:
            return {"status": "AUTO", "resolution": best[0][1][2], "similarity": round(float(best[0][0]), 2),
                    "matched_case": best[0][1][0]}
    cur = conn.execute("INSERT INTO cases(text, created) VALUES(?, ?)", (text, datetime.now().isoformat()))
    conn.commit()
    return {"status": "ESCALATE", "case_id": cur.lastrowid,
            "suggestions": [(r[2], round(float(s), 2)) for s, r in best if s >= 0.25]}

def resolve(conn, case_id, resolution, auto_ok=True):
    conn.execute("UPDATE cases SET resolution=?, auto_ok=? WHERE id=?", (resolution, int(auto_ok), case_id))
    conn.commit()

def mark_wrong(conn, case_id):
    """Admin says an auto-resolution was wrong: stop using that case for auto-solving."""
    conn.execute("UPDATE cases SET bad_auto=1 WHERE id=?", (case_id,)); conn.commit()
