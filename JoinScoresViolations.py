import pandas as pd


def main():
    # Read everything as strings. Beyond avoiding violation-code type mismatches,
    # this keeps already-published rows byte-identical: columns that are numeric
    # for PDF-sourced rows but blank for spreadsheet-sourced ones would otherwise
    # be inferred as float and rewrite every existing '1' as '1.0'.
    df_scores = pd.read_csv('food_scores_cleaned.csv', dtype=str)
    df_codes = pd.read_csv('CodeViolations.csv', dtype={'Violation Code': str})

    # Score is the one column that should be numeric in the published output.
    # Set it explicitly rather than relying on inference, so its formatting does
    # not shift when a new source writes it differently.
    df_scores['Score'] = pd.to_numeric(df_scores['Score'], errors='coerce')

    # Merge on violation codes (left join to keep all inspection records)
    df_merged = df_scores.merge(
        df_codes,
        how='left',
        left_on='Violations',
        right_on='Violation Code'
    )

    # Save the merged DataFrame to a new CSV file
    df_merged.to_csv('joined_scores_violations.csv', index=False)


if __name__ == '__main__':
    main()