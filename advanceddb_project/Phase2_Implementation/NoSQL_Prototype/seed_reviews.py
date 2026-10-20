"""Load the 60 synthetic reviews (and their replies subcollections) into Firestore.

    python seed_reviews.py            # upsert: safe to run again, same ids every time
    python seed_reviews.py --reset    # delete every review and reply first, then load

Credentials: see firestore_client.py / README.md.
"""
import argparse

from firestore_client import COLLECTION, REPLIES, get_db
from reviews_data import build_reviews

BATCH_LIMIT = 450        # Firestore allows 500 writes per batch; stay under it


def delete_all(db):
    deleted = 0
    for review in db.collection(COLLECTION).stream():
        # Firestore does not cascade: a subcollection survives its parent unless deleted too
        for reply in review.reference.collection(REPLIES).stream():
            reply.reference.delete()
            deleted += 1
        review.reference.delete()
        deleted += 1
    print(f'deleted {deleted} documents')


def seed(db):
    batch, pending = db.batch(), 0
    reviews = build_reviews()
    for review_id, doc, replies in reviews:
        ref = db.collection(COLLECTION).document(review_id)
        batch.set(ref, doc)
        pending += 1
        for reply_id, reply in replies:
            batch.set(ref.collection(REPLIES).document(reply_id), reply)
            pending += 1
        if pending >= BATCH_LIMIT:
            batch.commit()
            batch, pending = db.batch(), 0
    if pending:
        batch.commit()
    replies = sum(len(r[2]) for r in reviews)
    print(f'wrote {len(reviews)} reviews and {replies} replies to "{COLLECTION}"')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--reset', action='store_true', help='delete existing reviews and replies first')
    args = parser.parse_args()
    db = get_db()
    if args.reset:
        delete_all(db)
    seed(db)
    count = db.collection(COLLECTION).count().get()[0][0].value
    print(f'"{COLLECTION}" now holds {count} documents')


if __name__ == '__main__':
    main()
