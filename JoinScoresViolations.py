import pandas as pd


def main():
    # Read CSV files with violation codes as strings to avoid type mismatches
    df_scores = pd.read_csv('food_scores_cleaned.csv', dtype={'Violations': str})
    df_codes = pd.read_csv('CodeViolations.csv', dtype={'Violation Code': str})

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