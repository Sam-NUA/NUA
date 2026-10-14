import { generateDocketHTML, groupByCategory } from '../docket';
it('renders untrusted docket fields as text, including station, course and allergy names', () => {
  const hostile = '<img src=x onerror="alert(1)"><style>body{display:none}</style>';
  const html = generateDocketHTML({ id: hostile, orderId: hostile, printer: hostile,
    tableNumber: hostile, courseLabel: hostile, priority: hostile,
    items: [{ quantity: hostile, seat: hostile, productName: hostile, category: hostile,
      allergens: [hostile], dietary: [hostile], notes: hostile, course: 1, courseLabel: hostile }] });
  const doc = new DOMParser().parseFromString(html, 'text/html');
  expect(doc.querySelectorAll('img, script')).toHaveLength(0);
  expect(doc.querySelectorAll('style')).toHaveLength(1);
  expect(doc.body.textContent).toContain(hostile);
});
it('supports category names that collide with object prototype properties', () => {
  expect(groupByCategory([{ category: 'constructor', name: 'a' }, { category: '__proto__', name: 'b' }])).toHaveLength(2);
});
