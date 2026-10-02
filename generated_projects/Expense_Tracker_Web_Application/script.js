document.addEventListener('DOMContentLoaded', () => {
    const STORAGE_KEY = 'expense_tracker_expenses';

    // Model & Storage Helpers
    window.ExpenseModel = {
        getExpenses() {
            try {
                const data = localStorage.getItem(STORAGE_KEY);
                return data ? JSON.parse(data) : [];
            } catch (e) {
                console.error('Failed to parse expenses from localStorage:', e);
                return [];
            }
        },

        saveExpenses(expenses) {
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(expenses));
            } catch (e) {
                console.error('Failed to save expenses to localStorage:', e);
            }
        },

        validateExpense(expense) {
            const errors = [];
            
            if (!expense.description || typeof expense.description !== 'string' || expense.description.trim() === '') {
                errors.push('Description is required and must be a valid text.');
            }
            
            const numAmount = parseFloat(expense.amount);
            if (isNaN(numAmount) || numAmount <= 0) {
                errors.push('Amount must be a positive number greater than zero.');
            }
            
            if (!expense.date || isNaN(Date.parse(expense.date))) {
                errors.push('A valid date is required.');
            }
            
            if (!expense.category || expense.category.trim() === '') {
                errors.push('Category is required.');
            }

            return {
                isValid: errors.length === 0,
                errors
            };
        },

        addExpense(expenseData) {
            const validation = this.validateExpense(expenseData);
            if (!validation.isValid) {
                throw new Error(validation.errors.join(' '));
            }

            const expenses = this.getExpenses();
            const newExpense = {
                id: 'exp_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9),
                description: expenseData.description.trim(),
                amount: parseFloat(expenseData.amount),
                date: expenseData.date,
                category: expenseData.category
            };

            expenses.push(newExpense);
            this.saveExpenses(expenses);
            return newExpense;
        },

        deleteExpense(id) {
            let expenses = this.getExpenses();
            const initialLength = expenses.length;
            expenses = expenses.filter(exp => exp.id !== id);
            if (expenses.length !== initialLength) {
                this.saveExpenses(expenses);
                return true;
            }
            return false;
        },

        updateExpense(id, updatedData) {
            const validation = this.validateExpense(updatedData);
            if (!validation.isValid) {
                throw new Error(validation.errors.join(' '));
            }

            const expenses = this.getExpenses();
            const index = expenses.findIndex(exp => exp.id === id);
            if (index !== -1) {
                expenses[index] = {
                    id,
                    description: updatedData.description.trim(),
                    amount: parseFloat(updatedData.amount),
                    date: updatedData.date,
                    category: updatedData.category
                };
                this.saveExpenses(expenses);
                return expenses[index];
            }
            return null;
        }
    };

    console.log('Expense Tracker model and storage helpers initialized.');
});
