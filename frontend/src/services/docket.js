// Station docket printing (80mm thermal / browser print).
// Separate from services/printer.js, which formats the CUSTOMER receipt —
// a station docket is a kitchen-facing production ticket.

// "Bar Printer" -> "BAR", "Pizza Station" -> "PIZZA", "Kitchen Printer" -> "KITCHEN"
export function stationLabel(printerName) {
  return String(printerName || '')
    .replace(/\s*(printer|station)\s*$/i, '')
    .trim()
    .toUpperCase() || 'KITCHEN';
}

// Group a section's items by their category, preserving first-seen order.
export function groupByCategory(items) {
  const groups = [];
  const index = {};
  (items || []).forEach(item => {
    const cat = (item.category || 'Other').toUpperCase();
    if (!(cat in index)) {
      index[cat] = groups.length;
      groups.push({ category: cat, items: [] });
    }
    groups[index[cat]].items.push(item);
  });
  return groups;
}

// Group a section's items by course, in course order. Items without a course
// collapse into a single unlabelled group, so a venue that doesn't use
// coursing gets exactly the docket it got before.
export function groupByCourse(items) {
  const buckets = new Map();
  (items || []).forEach(item => {
    const key = item.course == null ? null : Number(item.course);
    if (!buckets.has(key)) buckets.set(key, { key, label: item.courseLabel || null, items: [] });
    buckets.get(key).items.push(item);
  });
  return [...buckets.values()].sort((a, b) => (a.key ?? 0) - (b.key ?? 0));
}

function itemRows(items, dim = false) {
  return (items || []).map(item => `
      <tr class="${dim ? 'dim' : ''}">
        <td class="qty">${item.quantity || 1}×</td>
        <td class="name">${item.seat ? `<span class="seat">S${item.seat}</span> ` : ''}${item.productName || item.name || ''}</td>
      </tr>
      ${(item.allergens || []).length ? `<tr class="${dim ? 'dim' : ''}"><td></td><td class="allergen">!! ${item.allergens.map(a => String(a).toUpperCase()).join(', ')}</td></tr>` : ''}
      ${(item.dietary || []).length ? `<tr class="${dim ? 'dim' : ''}"><td></td><td class="diet">(${item.dietary.join(', ')})</td></tr>` : ''}
      ${item.notes ? `<tr class="${dim ? 'dim' : ''}"><td></td><td class="note">» ${item.notes}</td></tr>` : ''}
  `).join('');
}

function categoryBlocks(items, dim = false) {
  return groupByCategory(items).map(g => `
      <div class="cat${dim ? ' dim' : ''}">${g.category}</div>
      <table>${itemRows(g.items, dim)}</table>
  `).join('');
}

// Courses outrank categories on a station docket: the station cooks a course
// at a time, and within it wants its categories together.
function courseBlocks(items, dim = false) {
  const courses = groupByCourse(items);
  const unlabelled = courses.length === 1 && courses[0].key == null;
  if (unlabelled) return categoryBlocks(items, dim);
  return courses.map(c => `
      <div class="course${dim ? ' dim' : ''}">${c.label || (c.key == null ? 'ORDER' : `COURSE ${c.key}`)}</div>
      ${categoryBlocks(c.items, dim)}
  `).join('');
}

// The docket prints the WHOLE order, category-wise: this station's own
// section first (full size — that's what it cooks), then every other
// section's items (dimmed, informational) so the station and the server
// see everything that goes out together. Bottom-left lists all sections,
// own station highlighted.
export function generateDocketHTML(job) {
  const own = stationLabel(job.printer);
  const stations = (job.orderStations && job.orderStations.length > 0
    ? job.orderStations : [job.printer]).map(stationLabel);
  const time = job.createdAt ? new Date(job.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

  // Own section first, then the rest in their fire order. Fall back to the
  // job's own items when a legacy job predates orderSections.
  const sections = (job.orderSections && job.orderSections.length > 0)
    ? job.orderSections
    : [{ printer: job.printer, items: job.items || [] }];
  const ownSection = sections.find(s => stationLabel(s.printer) === own) || { printer: job.printer, items: job.items || [] };
  const otherSections = sections.filter(s => stationLabel(s.printer) !== own);

  const othersHTML = otherSections.map(s => `
      <div class="other-station">${stationLabel(s.printer)}</div>
      ${courseBlocks(s.items, true)}
  `).join('');

  const stationChips = stations.map(s =>
    `<span class="chip${s === own ? ' own' : ''}">${s}</span>`
  ).join('');

  return `
    <!DOCTYPE html>
    <html>
    <head>
      <title>Docket ${job.orderId || job.id}</title>
      <style>
        body { font-family: 'Courier New', monospace; width: 80mm; margin: 0 auto; padding: 4mm; font-size: 13px; color: #000; }
        .station { text-align: center; font-size: 22px; font-weight: bold; letter-spacing: 2px; border: 2px solid #000; padding: 4px 0; }
        .meta { display: flex; justify-content: space-between; margin: 6px 0 2px; font-size: 12px; }
        .prio { font-weight: bold; }
        .sep { border-top: 1px dashed #000; margin: 5px 0; }
        table { width: 100%; border-collapse: collapse; }
        td { padding: 3px 0; vertical-align: top; }
        .qty { width: 34px; font-weight: bold; font-size: 15px; }
        .name { font-size: 15px; font-weight: bold; }
        .note { font-size: 11px; font-style: italic; }
        /* Allergens must be impossible to skim past — this is the one line on
           a docket where missing it has consequences beyond a remake. */
        .allergen { font-size: 12px; font-weight: bold; border: 2px solid #000; padding: 1px 3px; }
        .diet { font-size: 10px; }
        .cat { font-size: 11px; font-weight: bold; letter-spacing: 1px; border-bottom: 1px solid #000; margin-top: 6px; padding-bottom: 1px; }
        /* Other sections: printed for context, visually secondary */
        .also { margin-top: 8px; font-size: 10px; letter-spacing: 1px; text-align: center; border-top: 2px solid #000; padding-top: 4px; }
        .other-station { font-size: 12px; font-weight: bold; letter-spacing: 1px; margin-top: 6px; text-decoration: underline; }
        .cat.dim { font-weight: normal; }
        tr.dim .name { font-size: 12px; font-weight: normal; }
        tr.dim .qty { font-size: 12px; font-weight: normal; }
        /* Bottom-left sections strip: every section this order fires from */
        .sections { margin-top: 10px; text-align: left; }
        .sections .label { font-size: 10px; letter-spacing: 1px; }
        .chip { display: inline-block; border: 1px solid #000; padding: 1px 6px; margin: 2px 3px 0 0; font-size: 11px; font-weight: bold; }
        .chip.own { background: #000; color: #fff; }
        /* Course banner — the station is cooking one course at a time */
        .fired { text-align: center; font-size: 14px; font-weight: bold; letter-spacing: 2px; border: 1px solid #000; margin-top: 3px; padding: 2px 0; }
        .course { font-size: 13px; font-weight: bold; letter-spacing: 2px; margin-top: 8px; border-bottom: 2px solid #000; }
        .course.dim { font-weight: normal; border-bottom-width: 1px; }
        /* Seat number so a runner knows who gets what without asking */
        .seat { display: inline-block; border: 1px solid #000; padding: 0 3px; font-size: 11px; margin-right: 2px; }
      </style>
    </head>
    <body>
      <div class="station">${own}</div>
      ${job.courseLabel ? `<div class="fired">FIRE: ${job.courseLabel}</div>` : ''}
      <div class="meta">
        <span>${job.tableNumber ? `TABLE ${job.tableNumber}` : (job.orderId || '')}</span>
        <span class="prio">P${job.priority || 2}${time ? ` · ${time}` : ''}</span>
      </div>
      ${job.tableNumber && job.orderId ? `<div class="meta"><span>${job.orderId}</span></div>` : ''}
      <div class="sep"></div>
      ${courseBlocks(ownSection.items)}
      ${otherSections.length > 0 ? `
        <div class="also">— ALSO ON THIS ORDER —</div>
        ${othersHTML}
      ` : ''}
      <div class="sep"></div>
      <div class="sections">
        <div class="label">ORDER SECTIONS:</div>
        ${stationChips}
      </div>
    </body>
    </html>
  `;
}

export function printDocket(job) {
  // Lazy import — this module is called from hot order-entry paths and
  // the platform singleton is tiny, but keeping it out of this file's own
  // top-level import list avoids a circular-import risk with anything
  // under platform/ that might one day want docket formatting.
  import('../platform').then(({ PrintService }) => {
    PrintService.printHtml(generateDocketHTML(job));
  });
}
