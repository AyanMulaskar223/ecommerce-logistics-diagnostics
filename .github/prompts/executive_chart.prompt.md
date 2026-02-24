# Upgrade to Executive Seaborn Chart
Take the selected plotting code and upgrade it to a highly polished, executive-ready visualization using `seaborn` and `matplotlib`.

**Rules:**
1. Apply the enterprise theme: `sns.set_theme(style="whitegrid")`.
2. Ensure the chart has a clear, descriptive `plt.title()` explaining the business takeaway.
3. Remove top and right spines using `sns.despine()`.
4. Format the X and Y axis labels to be highly readable (e.g., rotating text if necessary, removing underscores from column names).
5. If representing currency, format the ticks as BRL (R$).
