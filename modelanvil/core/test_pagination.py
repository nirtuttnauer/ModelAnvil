"""Cursor pagination bounds, opaque cursors, and the public response shape."""
from base64 import b64decode
from urllib.parse import parse_qs, urlparse

from django.test import SimpleTestCase
from rest_framework.pagination import CursorPagination as FrameworkCursorPagination
from rest_framework.pagination import LimitOffsetPagination, PageNumberPagination
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from modelanvil.core.pagination import CursorPagination


class _Row:
    def __init__(self, created_at):
        self.created_at = created_at


class _MemoryQuery:
    """In-memory stand-in for the ordering, filter, and slice calls cursor pagination makes."""

    def __init__(self, rows):
        self._rows = list(rows)

    def order_by(self, *fields):
        rows = list(self._rows)
        for field in reversed(fields):
            reverse = field.startswith('-')
            name = field[1:] if reverse else field
            rows.sort(key=lambda row, name=name: getattr(row, name), reverse=reverse)
        return _MemoryQuery(rows)

    def filter(self, **lookups):
        kept = []
        for row in self._rows:
            if all(_matches(row, key, expected) for key, expected in lookups.items()):
                kept.append(row)
        return _MemoryQuery(kept)

    def __getitem__(self, item):
        return self._rows[item]


def _matches(row, key, expected):
    if key.endswith('__lt'):
        return getattr(row, key[:-4]) < expected
    if key.endswith('__gt'):
        return getattr(row, key[:-4]) > expected
    raise AssertionError(key)


def _request(query):
    return Request(APIRequestFactory().get('/items/', query))


def _cursor_query(url):
    parsed = urlparse(url)
    return parse_qs(parsed.query)


class CursorPaginationTests(SimpleTestCase):
    def test_bounds_use_cursor_pagination(self):
        paginator = CursorPagination()
        self.assertEqual(paginator.page_size, 50)
        self.assertEqual(paginator.max_page_size, 200)
        self.assertEqual(paginator.page_size_query_param, 'page_size')
        self.assertIsInstance(paginator, FrameworkCursorPagination)
        self.assertNotIsInstance(paginator, LimitOffsetPagination)
        self.assertNotIsInstance(paginator, PageNumberPagination)

    def test_paginated_response_includes_results_next_and_previous(self):
        rows = _MemoryQuery(_Row(f'{index:04d}') for index in range(3))
        paginator = CursorPagination()
        page = paginator.paginate_queryset(rows, _request({}))
        response = paginator.get_paginated_response([row.created_at for row in page])
        self.assertEqual(set(response.data), {'results', 'next', 'previous'})
        self.assertEqual(response.data['results'], ['0002', '0001', '0000'])
        self.assertIsNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_requested_page_size_above_max_is_capped_and_cursor_is_opaque(self):
        total = 250
        rows = _MemoryQuery(_Row(f'{index:04d}') for index in range(total))
        paginator = CursorPagination()
        page = paginator.paginate_queryset(rows, _request({'page_size': '1000'}))
        self.assertEqual(paginator.page_size, 200)
        self.assertEqual(len(page), 200)
        response = paginator.get_paginated_response([row.created_at for row in page])
        body = response.data
        self.assertEqual(set(body), {'results', 'next', 'previous'})
        self.assertIsNone(body['previous'])
        self.assertIsNotNone(body['next'])
        query = _cursor_query(body['next'])
        self.assertIn('cursor', query)
        self.assertNotIn('offset', query)
        self.assertNotIn('limit', query)
        self.assertNotIn('page', query)
        decoded = b64decode(query['cursor'][0].encode('ascii'), validate=True).decode('ascii')
        self.assertIn('p=', decoded)
        self.assertNotIn('offset', decoded)
        self.assertNotIn('limit', decoded)

        second = CursorPagination()
        next_query = {key: values[0] for key, values in query.items()}
        next_query['page_size'] = '1000'
        page_two = second.paginate_queryset(rows, _request(next_query))
        self.assertEqual(second.page_size, 200)
        self.assertEqual(len(page_two), total - 200)
        follow = second.get_paginated_response([row.created_at for row in page_two])
        self.assertIsNone(follow.data['next'])
        self.assertIsNotNone(follow.data['previous'])
        seen = body['results'] + follow.data['results']
        self.assertEqual(len(seen), total)
        self.assertEqual(len(set(seen)), total)
        self.assertEqual(seen, [f'{index:04d}' for index in range(total - 1, -1, -1)])
