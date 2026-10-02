# Wireframe & Layout Design

This document describes the visual layout and structure of the Expense Tracker Web Application.

## Overall Layout Structure

The application follows a single-page layout with a top header followed by a main container containing three main sections:

1. **Header**: Site title.
2. **Dashboard Section**: Summary cards and category breakdown.
3. **Expense Entry Form Section**: Form to add new expenses.
4. **Expense History List Section**: Table displaying recorded expenses with action buttons.

---

## Component Breakdown

### 1. Header
- **Location**: Top of the viewport, spanning full width.
- **Content**: Application title "Expense Tracker".
- **Visual Representation**: Dark background with white text, centered alignment, standard padding.

### 2. Dashboard Section
- **Location**: Below the header, at the top of the main content area.
- **Components**:
  - Section Header: "Dashboard"
  - Summary Cards Container: Horizontal flex container holding cards.
    - Total Expenses Card: Displays total sum of all expenses.
  - Category Breakdown Container: Grid container displaying individual category cards with their respective totals.
- **Visual Representation**: Clean card-based layout with light background, subtle shadows, and responsive grid for category breakdown.

### 3. Expense Entry Form Section
- **Location**: Middle of the main content area.
- **Components**:
  - Section Header: "Add New Expense"
  - Form Fields (Stacked vertically):
    - **Description**: Text input field.
    - **Amount**: Number input field (minimum 0.01).
    - **Date**: Date picker input.
    - **Category**: Dropdown select menu with options (Food, Transport, Housing, Entertainment, Utilities, Others).
    - **Submit Button**: Primary button labeled "Add Expense" spanning full width of the form.
- **Visual Representation**: Standard form styling with labels above inputs, adequate spacing between fields, and primary button styling.

### 4. Expense History List Section
- **Location**: Bottom of the main content area.
- **Components**:
  - Section Header: "Expense History"
  - Table Container: Responsive wrapper to allow horizontal scrolling on small screens.
    - **Table Headers**: Date, Description, Category, Amount, Actions.
    - **Table Body**: Dynamically populated rows representing each expense.
      - Each row contains:
        - Expense details (Date, Description, Category, Amount formatted as currency).
        - Action Controls: "Edit" and "Delete" buttons.
  - Empty State Message: Paragraph showing "No expenses recorded yet." when the list is empty.
- **Visual Representation**: Clean table design with borders, standard light borders, and small action buttons.

---

## Responsive Design Strategy

- **Desktop View (>= 768px)**:
  - Dashboard and Form sections are placed side-by-side (e.g., Dashboard on the left, Form on the right) or stacked vertically with Dashboard first.
  - The expense list spans full width of the container.
- **Mobile View (< 768px)**:
  - All sections stack vertically: Header -> Dashboard -> Form -> Expense List.
  - Form inputs and buttons stretch to 100% width for easy touch interaction.
  - Table becomes horizontally scrollable to prevent layout breakage.