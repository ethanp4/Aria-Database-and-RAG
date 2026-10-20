"""Firestore queries over the reviews collection.

    python queries.py

F1-F2 need the composite indexes in firestore.indexes.json and F4 the collection-group
index. Deploy them with `npx firebase-tools deploy --only firestore:indexes --project <id>`,
or follow the link in the error message Firestore returns the first time.
The emulator doesn't need indexes.
"""
from firestore_client import COLLECTION, REPLIES, get_db   # first: sets up warning filters
from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter
from google.cloud.firestore_v1.aggregation import AggregationQuery
from google.cloud.firestore_v1.base_query import Or


def most_reviewed_sku(db):
    counts = {}
    for doc in db.collection(COLLECTION).select(['product.sku']).stream():
        sku = doc.get('product.sku')
        counts[sku] = counts.get(sku, 0) + 1
    return max(sorted(counts), key=counts.get)


def main():
    db = get_db()
    reviews = db.collection(COLLECTION)
    sku = most_reviewed_sku(db)

    # F1  filter + ordering: the product page shows its published 4-5 star reviews, newest first
    print(f'\nF1  Published 4-5 star reviews of {sku}, newest first')
    query = (reviews
             .where(filter=FieldFilter('product.sku', '==', sku))
             .where(filter=FieldFilter('status', '==', 'published'))
             .where(filter=FieldFilter('rating', 'in', [4, 5]))
             .order_by('created_at', direction=firestore.Query.DESCENDING))
    for doc in query.stream():
        print(f'    {doc.id}  {doc.get("rating")}*  {doc.get("created_at"):%Y-%m-%d}  {doc.get("title")}')

    # F2  array membership + ordering: most helpful reviews that mention cold water
    print('\nF2  Most helpful reviews tagged "cold-water"')
    query = (reviews
             .where(filter=FieldFilter('tags', 'array_contains', 'cold-water'))
             .order_by('helpful_votes', direction=firestore.Query.DESCENDING)
             .limit(5))
    for doc in query.stream():
        print(f'    {doc.id}  {doc.get("helpful_votes"):>2} votes  {doc.get("product.name")}')

    # F3  aggregation: review count and average rating for one product, computed server side
    print(f'\nF3  Aggregates for {sku}')
    agg = AggregationQuery(reviews.where(filter=FieldFilter('product.sku', '==', sku)))
    agg.count(alias='reviews').avg('rating', alias='avg_rating')
    result = {r.alias: r.value for r in agg.get()[0]}
    print(f'    {result["reviews"]} reviews, average {result["avg_rating"]:.2f} stars')
    total = reviews.count().get()[0][0].value
    low = reviews.where(filter=Or([FieldFilter('rating', '==', 1), FieldFilter('rating', '==', 2)])).count().get()[0][0].value
    print(f'    whole collection: {total} reviews, {low} rated 1-2 stars')

    # F4  collection-group query: every staff reply across all reviews' replies subcollections
    print('\nF4  Staff replies across all reviews (collection group)')
    staff_replies = db.collection_group(REPLIES).where(filter=FieldFilter('author_role', '==', 'staff'))
    count = staff_replies.count().get()[0][0].value
    print(f'    {count} staff replies; first three:')
    for reply in staff_replies.limit(3).stream():
        review_id = reply.reference.parent.parent.id
        print(f'    {review_id}/{reply.id}  {reply.get("author")}: {reply.get("body")[:60]}')


if __name__ == '__main__':
    main()
