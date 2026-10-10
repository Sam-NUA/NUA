import React from 'react';
import { Search, Edit, Trash2, CheckSquare, Square, Download, ArrowUpDown, Filter as FilterIcon, ChevronUp, ChevronDown } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';

/**
 * Toolbar for the Products page: search, sort, status filter, layout toggle,
 * CSV export, category chips, bulk-action bar, and select-all checkbox.
 *
 * Pure presentational component — all state lives in the parent.
 */
export const ProductsToolbar = ({
  theme,
  searchTerm, setSearchTerm,
  sortKey, setSortKey,
  sortDir, setSortDir,
  filterStatus, setFilterStatus,
  layoutMode, setLayoutMode,
  exportCsv,
  filterCats, setFilterCats,
  categories,
  selected, clearSelection,
  allVisibleSelected, selectAllVisible,
  filteredProducts,
  onBulkEditOpen, onBulkDelete,
}) => (
  <div className="bg-white rounded-lg border p-3 space-y-3" data-testid="products-toolbar">
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={16} />
        <Input
          aria-label="Search products"
          placeholder="Search by name or SKU..."
          className="pl-9 h-9"
          value={searchTerm}
          onChange={e => setSearchTerm(e.target.value)}
          data-testid="product-search"
        />
      </div>
      <div className="flex items-center gap-1 text-xs">
        <ArrowUpDown size={14} className="text-gray-400" />
        <select
          className="border rounded p-1.5 text-xs"
          value={sortKey}
          onChange={e => setSortKey(e.target.value)}
          aria-label="Sort products by"
          data-testid="sort-key-select"
        >
          <option value="name">Name</option>
          <option value="category">Category</option>
          <option value="price">Price</option>
          <option value="stock">Stock</option>
          <option value="margin">Margin</option>
          <option value="recent">Recently edited</option>
        </select>
        <button
          onClick={() => setSortDir(sortDir === 'asc' ? 'desc' : 'asc')}
          className="border rounded p-1.5 hover:bg-gray-50"
          data-testid="sort-dir-toggle"
          title="Toggle direction"
        >
          {sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>
      <select
        className="border rounded p-1.5 text-xs"
        value={filterStatus}
        onChange={e => setFilterStatus(e.target.value)}
        aria-label="Product status"
        data-testid="filter-status-select"
      >
        <option value="all">All status</option>
        <option value="active">Active only</option>
        <option value="86">Only 86’d</option>
      </select>
      <div className="flex items-center border rounded overflow-hidden text-xs">
        <button
          onClick={() => setLayoutMode('grid')}
          className={`px-2 py-1 ${layoutMode === 'grid' ? 'text-white' : 'text-gray-500'}`}
          style={layoutMode === 'grid' ? { background: theme.primary } : {}}
          data-testid="view-grid"
        >Grid</button>
        <button
          onClick={() => setLayoutMode('table')}
          className={`px-2 py-1 ${layoutMode === 'table' ? 'text-white' : 'text-gray-500'}`}
          style={layoutMode === 'table' ? { background: theme.primary } : {}}
          data-testid="view-table"
        >Table</button>
      </div>
      <Button variant="outline" size="sm" onClick={exportCsv} className="h-9" data-testid="export-csv-btn">
        <Download size={14} className="mr-1.5" /> CSV
      </Button>
    </div>

    <div className="flex items-center gap-1.5 flex-wrap" data-testid="category-filter-chips">
      <FilterIcon size={12} className="text-gray-400" />
      <span className="text-[10px] uppercase tracking-widest text-gray-400">Category</span>
      <button
        onClick={() => setFilterCats([])}
        className={`px-2.5 py-1 text-xs rounded-full font-medium transition-colors ${filterCats.length === 0 ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
        style={filterCats.length === 0 ? { background: theme.primary } : {}}
        data-testid="filter-cat-all"
      >
        All
      </button>
      {categories.filter((c, index) => categories.findIndex(other => other.name === c.name) === index).map(c => {
        const ids = categories.filter(other => other.name === c.name).map(other => other.id);
        const on = ids.every(id => filterCats.includes(id));
        return (
          <button
            key={c.id}
            onClick={() => setFilterCats(on ? filterCats.filter(x => !ids.includes(x)) : [...new Set([...filterCats, ...ids])])}
            className={`px-2.5 py-1 text-xs rounded-full font-medium transition-colors ${on ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
            style={on ? { background: theme.primary } : {}}
            aria-pressed={on}
            data-testid={`filter-cat-${c.id}`}
          >
            {c.name}
          </button>
        );
      })}
    </div>

    {selected.size > 0 && (
      <div
        className="flex flex-wrap gap-3 items-center justify-between bg-amber-50 border border-amber-200 rounded px-3 py-2"
        data-testid="bulk-action-bar"
      >
        <span className="text-sm font-medium text-amber-900">
          {selected.size} selected
          <button
            onClick={clearSelection}
            className="ml-2 text-xs underline text-amber-700"
            data-testid="bulk-clear"
          >clear</button>
        </span>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={onBulkEditOpen} data-testid="bulk-edit-open">
            <Edit size={14} className="mr-1.5" /> Bulk Edit
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="text-red-600"
            onClick={onBulkDelete}
            data-testid="bulk-delete"
          >
            <Trash2 size={14} className="mr-1.5" /> Delete
          </Button>
        </div>
      </div>
    )}

    <div className="flex items-center gap-2 text-xs text-gray-500">
      <button
        onClick={allVisibleSelected ? clearSelection : selectAllVisible}
        className="flex items-center gap-1.5 hover:text-gray-800"
        data-testid="bulk-select-all"
      >
        {allVisibleSelected ? <CheckSquare size={14} /> : <Square size={14} />}
        Select all visible ({filteredProducts.length})
      </button>
    </div>
  </div>
);
