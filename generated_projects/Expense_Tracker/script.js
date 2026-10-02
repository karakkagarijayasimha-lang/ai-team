document.addEventListener('DOMContentLoaded', () => {
  const expenseForm = document.getElementById('expense-form');
  const descriptionInput = document.getElementById('description');
  const amountInput = document.getElementById('amount');
  const categoryInput = document.getElementById('category');
  const dateInput = document.getElementById('date');
  const expenseList = document.getElementById('expense-list');
  const totalAmountEl = document.getElementById('total-amount');
  const categoryBreakdownEl = document.getElementById('category-breakdown');

  let expenses = JSON.parse(localStorage.getItem('expenses')) || [];
  let editingId = null;

  // Set default date to today if creating new
  dateInput.valueAsDate = new Date();

  function saveAndRender() {
    localStorage.setItem('expenses', JSON.stringify(expenses));
    renderExpenses();
    renderSummary();
  }

  expenseForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const description = descriptionInput.value.trim();
    const amount = parseFloat(amountInput.value);
    const category = categoryInput.value;
    const date = dateInput.value;

    if (!description || isNaN(amount) || !category || !date) return;

    if (editingId !== null) {
      // Update existing expense
      expenses = expenses.map(exp => {
        if (exp.id === editingId) {
          return { id: exp.id, description, amount, category, date };
        }
        return exp;
      });
      editingId = null;
      expenseForm.querySelector('button[type="submit"]').textContent = 'Add Expense';
    } else {
      // Add new expense
      const newExpense = {
        id: Date.now().toString(),
        description,
        amount,
        category,
        date
      };
      expenses.push(newExpense);
    }

    expenseForm.reset();
    dateInput.valueAsDate = new Date();
    saveAndRender();
  });

  window.editExpense = function(id) {
    const expense = expenses.find(exp => exp.id === id);
    if (!expense) return;

    descriptionInput.value = expense.description;
    amountInput.value = expense.amount;
    categoryInput.value = expense.category;
    dateInput.value = expense.date;

    editingId = id;
    expenseForm.querySelector('button[type="submit"]').textContent = 'Update Expense';
    descriptionInput.focus();
  };

  window.deleteExpense = function(id) {
    if (confirm('Are you sure you want to delete this expense?')) {
      expenses = expenses.filter(exp => exp.id !== id);
      if (editingId === id) {
        editingId = null;
        expenseForm.reset();
        dateInput.valueAsDate = new Date();
        expenseForm.querySelector('button[type="submit"]').textContent = 'Add Expense';
      }
      saveAndRender();
    }
  };

  function renderExpenses() {
    expenseList.innerHTML = '';
    if (expenses.length === 0) {
      expenseList.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #777;">No expenses recorded yet.</td></tr>`;
      return;
    }

    // Sort by date descending
    const sortedExpenses = [...expenses].sort((a, b) => new Date(b.date) - new Date(a.date));

    sortedExpenses.forEach(exp => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escapeHtml(exp.description)}</td>
        <td>${escapeHtml(exp.category)}</td>
        <td>${escapeHtml(exp.date)}</td>
        <td>$${exp.amount.toFixed(2)}</td>
        <td>
          <div class="actions">
            <button class="btn-edit" onclick="editExpense('${exp.id}')">Edit</button>
            <button class="btn-delete" onclick="deleteExpense('${exp.id}')">Delete</button>
          </div>
        </td>
      `;
      expenseList.appendChild(tr);
    });
  }

  function renderSummary() {
    const total = expenses.reduce((sum, exp) => sum + exp.amount, 0);
    totalAmountEl.textContent = `$${total.toFixed(2)}`;

    const breakdown = {};
    expenses.forEach(exp => {
      breakdown[exp.category] = (breakdown[exp.category] || 0) + exp.amount;
    });

    categoryBreakdownEl.innerHTML = '';
    if (Object.keys(breakdown).length === 0) {
      categoryBreakdownEl.innerHTML = '<p style="color: #777; font-size: 14px;">No category breakdown available.</p>';
      return;
    }

    const ul = document.createElement('ul');
    ul.style.listStyle = 'none';
    ul.style.padding = '0';
    ul.style.marginTop = '10px';

    for (const [cat, amt] of Object.entries(breakdown)) {
      const li = document.createElement('li');
      li.style.display = 'flex';
      li.style.justifyContent = 'space-between';
      li.style.padding = '4px 0';
      li.style.fontSize = '14px';
      li.innerHTML = `<span><strong>${escapeHtml(cat)}:</strong></span> <span>$${amt.toFixed(2)}</span>`;
      ul.appendChild(li);
    }
    categoryBreakdownEl.appendChild(ul);
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initial render on load
  renderExpenses();
  renderSummary();
});
