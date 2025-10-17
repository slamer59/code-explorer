# Performance Testing Suite - Usage Guide

## Quick Start

### 1. Create Sample Data (for testing)

```bash
python perfo/create_sample_data.py
```

This creates minimal sample Parquet files in `perfo/output/` to verify the loader works.

### 2. Run Performance Test

```bash
python perfo/test_load.py
```

This will:
- Delete and recreate `perfo/test_db/`
- Create the full schema
- Load all Parquet files from `perfo/output/`
- Display detailed performance metrics

## Using Real Data

To test with real code-explorer graph data, you need to export your graph to Parquet first.

### Expected Parquet File Structure

Place your Parquet files in `perfo/output/`:

**Node files:**
- `files.parquet` - Columns: path (STRING), language (STRING), last_modified (TIMESTAMP), content_hash (STRING)
- `functions.parquet` - Columns: id, name, file, start_line, end_line, is_public, source_code
- `classes.parquet` - Columns: id, name, file, start_line, end_line, bases, is_public, source_code
- `variables.parquet` - Columns: id, name, file, definition_line, scope
- `imports.parquet` - Columns: id, imported_name, import_type, alias, line_number, is_relative, file
- `decorators.parquet` - Columns: id, name, file, line_number, arguments
- `attributes.parquet` - Columns: id, name, class_name, file, definition_line, type_hint, is_class_attribute
- `exceptions.parquet` - Columns: id, name, file, line_number
- `modules.parquet` - Columns: id, name, path, is_package, docstring

**Edge files:**
All edge files must have `src` and `dst` columns containing primary keys of source/destination nodes.

- `calls.parquet` - Additional columns: call_line
- `references.parquet` - Additional columns: line_number, context
- `contains_function.parquet` - File -> Function edges
- `contains_class.parquet` - File -> Class edges
- `contains_variable.parquet` - File -> Variable edges
- `imports_file.parquet` - File -> File edges, additional columns: line_number, is_direct
- `has_import.parquet` - File -> Import edges
- `module_of.parquet` - File -> Module edges
- `method_of.parquet` - Function -> Class edges
- `decorated_by.parquet` - Function -> Decorator edges, additional columns: position
- `accesses.parquet` - Function -> Attribute edges, additional columns: line_number, access_type
- `handles_exception.parquet` - Function -> Exception edges, additional columns: line_number, context
- `inherits.parquet` - Class -> Class edges
- `depends_on.parquet` - Class -> Class edges, additional columns: dependency_type, line_number
- `has_attribute.parquet` - Class -> Attribute edges
- `imports_from.parquet` - Import -> Function edges
- `contains_module.parquet` - Module -> Module edges

## Example Output

```
╭──────────────────────────────────────╮
│ KuzuDB Bulk Loading Performance Test │
│ Code Explorer Schema                 │
╰──────────────────────────────────────╯

Preparing database...
✓ Removed existing database
✓ Prepared database location
✓ Initializing KuzuDB

Creating database schema...
✓ Schema created in 0.0662s

Loading node tables...
✓ Loaded Function: 4 rows in 0.0484s (83 rows/sec)
✓ Loaded Class: 2 rows in 0.0367s (55 rows/sec)
...

Loading edge tables...
✓ Loaded CALLS: 3 edges in 0.0148s (202 edges/sec)
✓ Loaded REFERENCES: 2 edges in 0.0142s (141 edges/sec)
...

Database verification...
✓ Total nodes: 22
✓ Total edges: 17

[Performance tables displayed]

╭────────────────────────────────────────╮
│ ✓ Bulk loading completed successfully! │
╰────────────────────────────────────────╯
```

## Performance Metrics Explained

### Per-Table Metrics

- **Time (s)**: Wall-clock time to load that specific table
- **Rows**: Number of rows/edges loaded
- **Rows/sec**: Throughput rate (higher is better)

### Overall Metrics

- **Total Node Loading Time**: Sum of all node table loading times
- **Total Edge Loading Time**: Sum of all edge table loading times
- **Schema Creation Time**: Time to create all table schemas
- **Total Elapsed Time**: Schema + nodes + edges
- **Total Rows Loaded**: Sum of all rows across all tables
- **Overall Throughput**: Average loading speed across all data

## Known Issues

### TIMESTAMP Conversion Error

KuzuDB 0.11.2's `COPY FROM` may have issues with Arrow `timestamp[ns]` format from Parquet files.

**Workaround**: Store timestamps as INT64 (microseconds since epoch) and convert in KuzuDB:

```python
# In your export script:
timestamp_int64 = int(datetime.now().timestamp() * 1_000_000)
df['last_modified'] = timestamp_int64
```

### Foreign Key Constraints

Edge loading requires that all referenced nodes exist. If a node file fails to load, all edges referencing those nodes will also fail.

**Solution**: Ensure all node files are present and load successfully before edges.

## Benchmarking Tips

### For Realistic Performance Testing

1. **Use production-size data**: Small datasets (< 1000 rows) have overhead-dominated metrics
2. **Run multiple times**: First run includes JIT compilation overhead
3. **Check disk I/O**: Use SSD storage for optimal results
4. **Monitor resources**: Watch CPU and RAM usage during loading
5. **Disable other processes**: Minimize system load during benchmarking

### Expected Throughput

Typical COPY FROM performance on modern hardware (SSD, recent CPU):

- **Nodes**: 10,000 - 100,000 rows/sec (depending on column count and types)
- **Edges**: 50,000 - 200,000 edges/sec (simpler schema, faster loading)

For small test datasets (< 100 rows), expect lower throughput due to overhead.

## Troubleshooting

### "Output directory not found"

Create the directory:
```bash
mkdir -p perfo/output
```

Then either run `create_sample_data.py` or copy your Parquet files there.

### "Unable to find primary key value"

This means an edge references a node that doesn't exist. Check:
1. Node file loaded successfully
2. Primary key values in edge file match exactly
3. No typos in file paths or IDs

### "Conversion exception"

Schema mismatch between Parquet file and KuzuDB table. Verify:
1. Column names match exactly
2. Data types are compatible
3. No NULL values in PRIMARY KEY columns

### Low Throughput (< 100 rows/sec)

Possible causes:
1. Running on slow storage (HDD vs SSD)
2. Small dataset with overhead-dominated performance
3. Debug builds (use release builds for production)
4. System resource contention

## Advanced Usage

### Custom Schema

To test a different schema, modify `test_load.py`:

1. Update `NODE_TABLES` and `EDGE_TABLES` lists
2. Modify `create_schema()` function with your DDL
3. Ensure Parquet files match your schema

### Comparing Versions

To benchmark different KuzuDB versions:

```bash
# Test version A
uv pip install kuzu==0.11.2
python perfo/test_load.py > results_0.11.2.txt

# Test version B
uv pip install kuzu==0.12.0
python perfo/test_load.py > results_0.12.0.txt

# Compare results
diff -u results_0.11.2.txt results_0.12.0.txt
```

### Profiling

To identify bottlenecks:

```bash
python -m cProfile -o profile.stats perfo/test_load.py
python -m pstats profile.stats
```

## Integration with CI/CD

### Performance Regression Testing

Add to your CI pipeline:

```yaml
- name: Performance Test
  run: |
    python perfo/create_sample_data.py
    python perfo/test_load.py | tee perf_results.txt

- name: Check Performance
  run: |
    # Fail if loading takes > 5 seconds
    TOTAL_TIME=$(grep "Total Elapsed Time" perf_results.txt | awk '{print $4}' | sed 's/s//')
    if (( $(echo "$TOTAL_TIME > 5.0" | bc -l) )); then
      echo "Performance regression detected!"
      exit 1
    fi
```

## Next Steps

1. **Export your graph**: Create an export script to dump your `.code-explorer/graph.db` to Parquet
2. **Run real benchmarks**: Test with production-size data
3. **Optimize schema**: Based on results, consider schema changes for better performance
4. **Compare approaches**: Test COPY FROM vs batch INSERT vs transaction batching
