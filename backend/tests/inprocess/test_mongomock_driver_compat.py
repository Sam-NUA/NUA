"""The mock must execute ordinary writes and reject unsupported sort semantics."""
import mongomock
import pytest
from pymongo import UpdateOne


def test_bulk_update_executes_with_current_driver():
    collection = mongomock.MongoClient().compat.items
    collection.insert_one({'_id': 'stock', 'quantity': 3})
    result = collection.bulk_write([
        UpdateOne({'_id': 'stock'}, {'$inc': {'quantity': -1}}),
    ])
    assert result.modified_count == 1
    assert collection.find_one({'_id': 'stock'})['quantity'] == 2


def test_sorted_bulk_update_is_not_silently_ignored():
    collection = mongomock.MongoClient().compat.items
    collection.insert_one({'_id': 'stock', 'quantity': 3})
    with pytest.raises(NotImplementedError, match='real MongoDB'):
        collection.bulk_write([
            UpdateOne({}, {'$inc': {'quantity': -1}}, sort={'quantity': 1}),
        ])
    assert collection.find_one({'_id': 'stock'})['quantity'] == 3
