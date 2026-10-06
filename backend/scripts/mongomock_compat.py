"""Test-only compatibility for PyMongo's optional bulk-update sort argument."""
import inspect

from mongomock.collection import BulkOperationBuilder


def install():
    original = BulkOperationBuilder.add_update
    if 'sort' in inspect.signature(original).parameters:
        return

    def add_update(self, selector, doc, multi=False, upsert=False,
                   collation=None, array_filters=None, hint=None, sort=None):
        # PyMongo now always passes sort, even when it is unused. Do not
        # pretend to support sorted updates: those require a real Mongo test.
        if sort is not None:
            raise NotImplementedError('Sorted bulk updates require real MongoDB')
        return original(self, selector, doc, multi=multi, upsert=upsert,
                        collation=collation, array_filters=array_filters, hint=hint)

    BulkOperationBuilder.add_update = add_update
