"""
Cleans the global sustainable energy data for the Tableau dashboard.

Outputs (both .csv and .xlsx):
  sustainable-energy-clean   main cleaned dataset, one row per country-year
  global-mix-by-year         electricity mix (TWh) per year, for the stacked area chart
  renewable-share-delta      renewable share 2000 vs 2019 per country, for the slope/bar charts

Note: the renewable-share % column only has full coverage up to 2019, so all
before/after comparisons use 2000 -> 2019. The TWh columns run through 2020.

Usage: python clean_energy_data.py
"""

import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RAW_FILE = os.path.join(BASE_DIR, 'global-data-on-sustainable-energy.csv')
CONTINENT_FILE = os.path.join(BASE_DIR, 'continent-mapping.csv')

CLEAN_FILE = os.path.join(BASE_DIR, 'sustainable-energy-clean.csv')
GLOBAL_MIX_FILE = os.path.join(BASE_DIR, 'global-mix-by-year.csv')
DELTA_FILE = os.path.join(BASE_DIR, 'renewable-share-delta.csv')

BASELINE_YEAR = 2000
LATEST_YEAR = 2019

# World Bank-style GDP-per-capita brackets (USD).
INCOME_BANDS = [
    (0,      1_086,  'Low'),
    (1_086,  4_256,  'Lower-Middle'),
    (4_256,  13_206, 'Upper-Middle'),
    (13_206, 1e12,   'High'),
]

# Raw column names have spaces, units, and a literal "\n" in the density header.
COLUMN_RENAMES = {
    'Entity': 'Country',
    'Year': 'Year',
    'Renewable-electricity-generating-capacity-per-capita': 'RenewableCapacityPerCapita',
    'Access to electricity (% of population)': 'ElectricityAccessPct',
    'Access to clean fuels for cooking': 'CleanFuelsAccessPct',
    'Financial flows to developing countries (US $)': 'FinancialFlowsUSD',
    'Renewable energy share in the total final energy consumption (%)': 'RenewableSharePct',
    'Electricity from fossil fuels (TWh)': 'ElectricityFossilTWh',
    'Electricity from nuclear (TWh)': 'ElectricityNuclearTWh',
    'Electricity from renewables (TWh)': 'ElectricityRenewablesTWh',
    'Low-carbon electricity (% electricity)': 'LowCarbonElectricityPct',
    'Primary energy consumption per capita (kWh/person)': 'PrimaryEnergyPerCapitaKWh',
    'Energy intensity level of primary energy (MJ/$2017 PPP GDP)': 'EnergyIntensity',
    'Value_co2_emissions_kt_by_country': 'CO2EmissionsKt',
    'Renewables (% equivalent primary energy)': 'RenewablesPrimaryPct',
    'gdp_growth': 'GDPGrowth',
    'gdp_per_capita': 'GDPPerCapita',
    r'Density\n(P/Km2)': 'DensityPerKm2',
    'Land Area(Km2)': 'LandAreaKm2',
    'Latitude': 'Latitude',
    'Longitude': 'Longitude',
}


def load_continent_mapping(path):
    mapping = pd.read_csv(path)
    return dict(zip(mapping['Country'], mapping['Continent']))


def assign_income_band(gdp_per_capita):
    if pd.isna(gdp_per_capita):
        return None
    for low, high, label in INCOME_BANDS:
        if low <= gdp_per_capita < high:
            return label
    return None


def load_and_rename_raw(path):
    df = pd.read_csv(path).rename(columns=COLUMN_RENAMES)

    missing = set(COLUMN_RENAMES.values()) - set(df.columns)
    if missing:
        raise ValueError(f'Expected columns missing after rename: {missing}')

    return df


def add_derived_columns(df, continent_map):
    df['DensityPerKm2'] = pd.to_numeric(
        df['DensityPerKm2'].astype(str).str.replace(',', '', regex=False),
        errors='coerce',
    )

    df['Population'] = df['DensityPerKm2'] * df['LandAreaKm2']

    df['Continent'] = df['Country'].map(continent_map)
    unmapped = df.loc[df['Continent'].isna(), 'Country'].unique()
    if len(unmapped) > 0:
        raise ValueError(
            f'{len(unmapped)} countries have no continent mapping: '
            f'{sorted(unmapped)[:10]}... Update continent-mapping.csv.'
        )

    df['IncomeBand'] = df['GDPPerCapita'].apply(assign_income_band)

    return df


def build_global_mix(df):
    """Electricity TWh per year by source, in long form for the stacked area chart."""
    yearly = (
        df.groupby('Year')[['ElectricityFossilTWh',
                            'ElectricityNuclearTWh',
                            'ElectricityRenewablesTWh']]
        .sum(min_count=1)
        .reset_index()
    )

    long_form = yearly.melt(
        id_vars='Year',
        var_name='Source',
        value_name='TWh',
    )

    long_form['Source'] = long_form['Source'].map({
        'ElectricityFossilTWh': 'Fossil Fuels',
        'ElectricityNuclearTWh': 'Nuclear',
        'ElectricityRenewablesTWh': 'Renewables',
    })

    return long_form


def build_renewable_share_delta(df, continent_map):
    """One row per country: renewable share in 2000 vs 2019 plus the delta.

    Countries missing either year are dropped so the comparison is fair.
    """
    pivot = (
        df[df['Year'].isin([BASELINE_YEAR, LATEST_YEAR])]
        .pivot(index='Country', columns='Year', values='RenewableSharePct')
    )
    pivot.columns = [f'RenewableShare{int(c)}' for c in pivot.columns]
    pivot = pivot.dropna()

    pivot['DeltaPP'] = (pivot[f'RenewableShare{LATEST_YEAR}']
                        - pivot[f'RenewableShare{BASELINE_YEAR}'])

    latest_gdp = (
        df[df['Year'] == LATEST_YEAR]
        .set_index('Country')[['GDPPerCapita', 'IncomeBand']]
    )
    pivot = pivot.join(latest_gdp)
    pivot['Continent'] = pivot.index.map(continent_map)

    return pivot.reset_index().round(2)


def write_outputs(df, path_csv):
    """Write both .csv (for inspection) and .xlsx (for Tableau)."""
    df.to_csv(path_csv, index=False)
    df.to_excel(path_csv.replace('.csv', '.xlsx'), index=False)


def main():
    df = load_and_rename_raw(RAW_FILE)
    print(f'Loaded {len(df):,} rows, {df["Country"].nunique()} countries, '
          f'{df["Year"].min()}-{df["Year"].max()}')

    continent_map = load_continent_mapping(CONTINENT_FILE)
    df = add_derived_columns(df, continent_map)
    write_outputs(df, CLEAN_FILE)
    print(f'Wrote {os.path.basename(CLEAN_FILE)} ({len(df):,} rows)')

    global_mix = build_global_mix(df)
    write_outputs(global_mix, GLOBAL_MIX_FILE)
    print(f'Wrote {os.path.basename(GLOBAL_MIX_FILE)} ({len(global_mix)} rows)')

    delta = build_renewable_share_delta(df, continent_map)
    write_outputs(delta, DELTA_FILE)
    print(f'Wrote {os.path.basename(DELTA_FILE)} ({len(delta)} countries)')

    print('\nTop 5 risers in renewable share (percentage points):')
    print(delta.nlargest(5, 'DeltaPP')[['Country', 'Continent',
                                       f'RenewableShare{BASELINE_YEAR}',
                                       f'RenewableShare{LATEST_YEAR}',
                                       'DeltaPP']].to_string(index=False))


if __name__ == '__main__':
    main()
