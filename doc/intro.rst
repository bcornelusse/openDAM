============
Introduction
============

This Python package is an open source implementation of formulations and algorithms for the European day-ahead market coupling problem.

It is based on scientific articles, published or under review, authored by (in random order) Mehdi Madani, Mathieu Van Vyve, Iacopo Savelli,
Antonio Giannitrapani, Simone Paoletti, Antonio Vicino and Bertrand Cornélusse.

It includes functionalities for

 * organizing market data (e.g. convert CSV data into an sqlite database, or import historical date from the Italian market operator, GME)
 * solving the market coupling problems with specificities of some European countries such as complex orders from the Iberian market, the PUN of the Italian market, etc.
 * exporting the results in CSV format.

Although it can deal with some real-sized instances, the implementation is by no means optimized,
and significant time reductions can probably be obtained by speeding up the model creation process
(currently using the pyomo package for MIP modelling), implementing fast heuristics for finding good initial solutions, etc.

Several rules and market products from the full set of the European day-ahead market are not implemented, such as:
 * smart orders (linked blocks, etc.)
 * the "flow-based" market model
 * price and volume indeterminacy lifting rules

Finally, although it is feasible, it is not directly possible to have both complex orders and the PUN in a region (both implementations are separate for now).
