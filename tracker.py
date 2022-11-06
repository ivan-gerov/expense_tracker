import os
import json
from collections import OrderedDict

import pandas as pd
from fuzzywuzzy import fuzz

MERCHANT_MAPPING = "merchant_category_mapping.json"
EXPENSE_CATEGORY_FAMILY_MAPPING = "expense_category_family_mapping.json"

STATEMENTS_DIR = "./statements"
EXPENSE_REPORTS_DIR = "./expense_reports"


class ExpenseTracker:
    def __init__(
        self,
        statement="",
        statements_dir=STATEMENTS_DIR,
        merchant_mapping=MERCHANT_MAPPING,
        expense_category_family_mapping=EXPENSE_CATEGORY_FAMILY_MAPPING,
    ):
        self.statements_dir = statements_dir
        self.statement_name = statement or self.select_statement()
        self.statement = pd.read_csv(
            os.path.join(self.statements_dir, self.statement_name)
        )

        # Load mappings
        with open(merchant_mapping) as f:
            self.merchant_mapping = json.load(f)

        with open(expense_category_family_mapping) as f:
            self.expense_category_family_mapping = json.load(f)

    def process_transactions(self):
        # Fix Transaction Date type
        self.statement["Transaction Date"] = pd.to_datetime(
            self.statement["Transaction Date"], format="%d/%m/%Y"
        )

        # Drop credits
        self.statement = self.statement.loc[pd.isnull(self.statement["Credit Amount"])]
        self.statement.drop("Credit Amount", axis=1, inplace=True)

        # Add merchant category
        self.statement = self.statement.apply(self.add_merchant_category, axis=1)

        # Get unrecognized merchants
        unrecognized_merchants = set()
        if self.statement["Category"].isnull().values.any():
            self.statement.apply(
                lambda row: pd.isnull(row["Category"])
                and unrecognized_merchants.add(row["Transaction Description"]),
                axis=1,
            )

        # Process unrecognized transactions
        self.process_unrecognized_merchants(unrecognized_merchants)

        # Add category family
        self.statement = self.statement.apply(self.add_category_family, axis=1)

    def make_reports(self, expense_reports_dir=EXPENSE_REPORTS_DIR):
        def make_markdown_multicode(string):
            return f"```\n{string}\n```"

        expense_report_date_range = self.get_date_range_from_statement(self.statement)
        expense_report_name = f"expense_report_{expense_report_date_range}"
        with open(
            os.path.join(expense_reports_dir, f"{expense_report_name}.md"), "w"
        ) as expense_report:
            expense_report.write(
                "\n".join(
                    [
                        f"# Expense report for {expense_report_date_range}",
                        "\n",
                        "### Category families",
                        make_markdown_multicode(
                            self.get_expenses_by_category_families(
                                self.statement
                            ).to_string(index=False)
                        ),
                        "\n",
                        "### Extended view",
                        make_markdown_multicode(
                            self.statement.groupby(["Category"])
                            .sum(numeric_only=True)["Debit Amount"]
                            .reset_index()
                            .to_string(index=False)
                        ),
                    ]
                )
            )

    @staticmethod
    def get_expenses_by_category_families(df: pd.DataFrame) -> pd.DataFrame:
        df = (
            df.groupby(["Category Family"])
            .sum(numeric_only=True)["Debit Amount"]
            .reset_index()
            .copy()
        )
        df["Percentage"] = round(
            (df["Debit Amount"] / df["Debit Amount"].sum()) * 100, 0
        )
        return df

    def select_statement(self):
        """CLI command to select the statement manually
        from a list of statements ordered by date descending."""
        statements = OrderedDict(
            {
                str(id_ + 1): statement
                for id_, statement in enumerate(
                    sorted(
                        os.listdir(self.statements_dir),
                        # Sort statements by last modified
                        key=lambda x: os.path.getmtime(
                            os.path.join(self.statements_dir, x)
                        ),
                        reverse=True,
                    )
                )
            }
        )
        for id_, statement in statements.items():
            print(f"{id_} - {statement}")
        selected_statement_id = input("Please select a statement id: ")
        return statements[selected_statement_id]

    def add_merchant_category(self, row):
        """Add merchant category according to mapping"""
        row["Category"] = self.merchant_mapping.get(row["Transaction Description"])
        return row

    def process_unrecognized_merchants(self, merchants):
        still_unrecognized = []
        for merchant in merchants:
            merchant_matched = False
            for mapped_merchant in self.merchant_mapping:
                if fuzz.ratio(merchant.lower(), mapped_merchant.lower()) >= 80:
                    self.merchant_mapping.update(
                        {merchant: self.merchant_mapping[mapped_merchant]}
                    )
                    merchant_matched = True
                    break
            if not merchant_matched:
                still_unrecognized.append(merchant)

        with open(MERCHANT_MAPPING, "w") as f:
            json.dump(self.merchant_mapping, f, indent=4)

        if still_unrecognized:
            print("These merchants are unrecognized!: ")
            for merchant in still_unrecognized:
                print(merchant)

    def add_category_family(self, row):
        for category_family, children in self.expense_category_family_mapping.items():
            if row["Category"] in children:
                row["Category Family"] = category_family
                break
            else:
                row["Category Family"] = "Wants"
        return row

    @staticmethod
    def get_date_range_from_statement(statement):
        sorted_statement = statement.copy().sort_values(
            "Transaction Date",
        )
        start_date, end_date = [
            sorted_statement["Transaction Date"]
            .dt.strftime("%b_%d_%Y")
            .iloc[date_index]
            for date_index in [0, -1]
        ]
        return f"{start_date}_{end_date}"


if __name__ == "__main__":
    expense_tracker = ExpenseTracker()
    expense_tracker.process_transactions()
    expense_tracker.make_reports()
