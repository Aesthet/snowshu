import networkx as nx
import pandas as pd

import snowshu.core.models.data_types as dt
from snowshu.adapters.source_adapters.snowflake_adapter import SnowflakeAdapter
from snowshu.core.compile import RuntimeSourceCompiler
from snowshu.core.models.attribute import Attribute
from snowshu.core.models.relation import Relation
from snowshu.samplings.sample_methods import BernoulliSampleMethod
from snowshu.samplings.samplings import DefaultSampling
from tests.common import query_equalize
from tests.conftest import RelationTestHelper


def stub_out_sampling(rel:Relation)->Relation:
    rel.sampling=DefaultSampling()
    rel.sampling.sample_method=BernoulliSampleMethod(1500,units='rows')
    return rel


def test_analyze_unsampled(stub_relation_set):
    upstream = stub_relation_set.upstream_relation
    upstream.unsampled = True
    dag = nx.DiGraph()
    dag.add_edges_from([(upstream, stub_relation_set.downstream_relation,)])
    adapter = SnowflakeAdapter()
    upstream = RuntimeSourceCompiler.compile_queries_for_relation(upstream, dag, adapter, True)
    assert query_equalize(upstream.compiled_query) == query_equalize(f"""
        WITH
            {upstream.scoped_cte('SNOWSHU_COUNT_POPULATION')} AS (
        SELECT
            COUNT(*) AS population_size
        FROM
            {upstream.quoted_dot_notation}
        )
        ,{upstream.scoped_cte('SNOWSHU_CORE_SAMPLE')} AS (
        SELECT
            *
        FROM
            {upstream.quoted_dot_notation}
        )
        ,{upstream.scoped_cte('SNOWSHU_CORE_SAMPLE_COUNT')} AS (
        SELECT
            COUNT(*) AS sample_size
        FROM
            {upstream.scoped_cte('SNOWSHU_CORE_SAMPLE')}
        )
        SELECT
            s.sample_size AS sample_size
            ,p.population_size AS population_size
        FROM
            {upstream.scoped_cte('SNOWSHU_CORE_SAMPLE_COUNT')} s
        INNER JOIN
            {upstream.scoped_cte('SNOWSHU_COUNT_POPULATION')} p
        ON
            1=1
        LIMIT 1
    """)


def test_run_unsampled(stub_relation_set):
    upstream = stub_relation_set.upstream_relation
    upstream.unsampled = True
    dag = nx.DiGraph()
    dag.add_edges_from([(upstream, stub_relation_set.downstream_relation,)])
    adapter = SnowflakeAdapter()
    upstream = RuntimeSourceCompiler.compile_queries_for_relation(upstream, dag, adapter, False)
    assert query_equalize(upstream.compiled_query) == query_equalize(f"""
        SELECT
            *
        FROM {upstream.quoted_dot_notation}
    """)


def test_analyze_iso(stub_relation_set):
    iso = stub_relation_set.iso_relation
    iso = stub_out_sampling(iso)
    dag = nx.DiGraph()
    dag.add_nodes_from([iso])
    adapter = SnowflakeAdapter()
    iso = RuntimeSourceCompiler.compile_queries_for_relation(iso, dag, adapter, True)
    assert query_equalize(iso.compiled_query) == query_equalize(f"""
        WITH
            {iso.scoped_cte('SNOWSHU_COUNT_POPULATION')} AS (
        SELECT
            COUNT(*) AS population_size
        FROM
            {iso.quoted_dot_notation}
        )
        ,{iso.scoped_cte('SNOWSHU_CORE_SAMPLE')} AS (
        SELECT
            *
        FROM 
            {iso.quoted_dot_notation}
            SAMPLE BERNOULLI (1500 ROWS)
        )
        ,{iso.scoped_cte('SNOWSHU_CORE_SAMPLE')}_COUNT AS (
        SELECT
            COUNT(*) AS sample_size
        FROM
            {iso.scoped_cte('SNOWSHU_CORE_SAMPLE')}
        )
        SELECT
            s.sample_size AS sample_size
            ,p.population_size AS population_size
        FROM
            {iso.scoped_cte('SNOWSHU_CORE_SAMPLE')}_COUNT s
        INNER JOIN
            {iso.scoped_cte('SNOWSHU_COUNT_POPULATION')} p
        ON
            1=1
        LIMIT 1
        """)


def test_run_iso(stub_relation_set):
    iso = stub_relation_set.iso_relation
    iso = stub_out_sampling(iso)
    dag = nx.DiGraph()
    dag.add_nodes_from([iso])
    adapter = SnowflakeAdapter()
    iso = RuntimeSourceCompiler.compile_queries_for_relation(iso, dag, adapter, False)
    assert query_equalize(iso.compiled_query) == query_equalize(f"""
        SELECT
            *
        FROM 
            {iso.quoted_dot_notation}
            SAMPLE BERNOULLI (1500 ROWS)
        """)


def test_run_deps_polymorphic_idtype(stub_relation_set):
    child1 = stub_relation_set.child_relation_type_1
    child2 = stub_relation_set.child_relation_type_2
    child3 = stub_relation_set.child_relation_type_3
    parent = stub_relation_set.parent_relation_childid_type
    childid = stub_relation_set.childid_key
    childtype = stub_relation_set.childtype_key
    child2type_override = stub_relation_set.child2override_key
    local_overrides = {child2.dot_notation: child2type_override}
    for relation in (child1, child2, child3, parent,):
        relation = stub_out_sampling(relation)

    child1.data=pd.DataFrame([{childid: "1"},{childid: "2"}])
    child2.data=pd.DataFrame([{childid: "1"},{childid: "3"}])
    child3.data=pd.DataFrame([{childid: "1"},{childid: "4"}])
    dag=nx.DiGraph()
    dag.add_edge(child1,parent,direction="polymorphic",remote_attribute=childid,local_attribute=childid,
        local_type_attribute=childtype,local_type_overrides=local_overrides)
    dag.add_edge(child2,parent,direction="polymorphic",remote_attribute=childid,local_attribute=childid,
        local_type_attribute=childtype,local_type_overrides=local_overrides)
    dag.add_edge(child3,parent,direction="polymorphic",remote_attribute=childid,local_attribute=childid,
        local_type_attribute=childtype,local_type_overrides=local_overrides)
    adapter=SnowflakeAdapter()
    child1 = RuntimeSourceCompiler.compile_queries_for_relation(child1,dag,adapter,False)
    child2 = RuntimeSourceCompiler.compile_queries_for_relation(child2,dag,adapter,False)
    child3 = RuntimeSourceCompiler.compile_queries_for_relation(child3,dag,adapter,False)
    parent = RuntimeSourceCompiler.compile_queries_for_relation(parent,dag,adapter,False)

    expected_query = f"""
        SELECT 
            * 
        FROM 
        {parent.quoted_dot_notation}
        WHERE ( ({childid} IN ('1','2') AND LOWER({childtype}) = LOWER('child_type_1_record') ) OR ({childid} IN ('1','3') AND LOWER({childtype}) = LOWER('{child2type_override}') ) OR ({childid} IN ('1','4') AND LOWER({childtype}) = LOWER('child_type_3_record') ) )
    """
    assert query_equalize(parent.compiled_query)==query_equalize(expected_query)

def test_run_deps_polymorphic_parentid(stub_relation_set):
    child1 = stub_relation_set.child_relation_type_1
    child2 = stub_relation_set.child_relation_type_2
    child3 = stub_relation_set.child_relation_type_3
    parent = stub_relation_set.parent_relation_parentid
    parentid = stub_relation_set.parentid_key
    for relation in (child1, child2, child3, parent,):
        relation = stub_out_sampling(relation)

    child1.data=pd.DataFrame([{parentid: "1"},{parentid: "10"}])
    child2.data=pd.DataFrame([{parentid: "2"},{parentid: "20"}])
    child3.data=pd.DataFrame([{parentid: "3"},{parentid: "30"}])
    dag=nx.DiGraph()
    dag.add_edge(child1,parent,direction="polymorphic",remote_attribute=parentid,local_attribute=parentid)
    dag.add_edge(child2,parent,direction="polymorphic",remote_attribute=parentid,local_attribute=parentid)
    dag.add_edge(child3,parent,direction="polymorphic",remote_attribute=parentid,local_attribute=parentid)
    adapter=SnowflakeAdapter()
    child1 = RuntimeSourceCompiler.compile_queries_for_relation(child1,dag,adapter,False)
    child2 = RuntimeSourceCompiler.compile_queries_for_relation(child2,dag,adapter,False)
    child3 = RuntimeSourceCompiler.compile_queries_for_relation(child3,dag,adapter,False)
    parent = RuntimeSourceCompiler.compile_queries_for_relation(parent,dag,adapter,False)

    expected_query = f"""
        SELECT 
            * 
        FROM 
        {parent.quoted_dot_notation}
        WHERE ( {parentid} IN ('1','10') OR {parentid} IN ('2','20') OR {parentid} IN ('3','30') )
    """
    assert query_equalize(parent.compiled_query)==query_equalize(expected_query)


def test_run_deps_directional(stub_relation_set):
    upstream=stub_relation_set.upstream_relation
    downstream=stub_relation_set.downstream_relation
    for relation in (downstream,upstream,):
        relation.attributes=[Attribute('id',dt.INTEGER)]
        relation=stub_out_sampling(relation)
    upstream.data=pd.DataFrame([dict(id=1),dict(id=2),dict(id=3)])
    dag=nx.DiGraph()
    dag.add_edge(upstream,downstream,direction="directional",remote_attribute='id',local_attribute='id')
    adapter=SnowflakeAdapter()
    upstream = RuntimeSourceCompiler.compile_queries_for_relation(upstream,dag,adapter,False)
    downstream = RuntimeSourceCompiler.compile_queries_for_relation(downstream,dag,adapter,False)
    assert query_equalize(downstream.compiled_query)==query_equalize(f"""
        WITH 
        {downstream.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {downstream.quoted_dot_notation}
        WHERE id IN (1,2,3) 
        )
        ,{downstream.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {downstream.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {downstream.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)


def test_run_deps_bidirectional_include_outliers(stub_relation_set):
    upstream=stub_relation_set.upstream_relation
    downstream=stub_relation_set.downstream_relation
    for relation in (downstream,upstream,):
        relation.attributes=[Attribute('id',dt.INTEGER)]
        relation.include_outliers=True
        relation.max_number_of_outliers=100
        relation=stub_out_sampling(relation)
    upstream.data=pd.DataFrame([dict(id=1),dict(id=2),dict(id=3)])

    dag=nx.DiGraph()
    dag.add_edge(upstream,downstream,direction="bidirectional",remote_attribute='id',local_attribute='id')
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(upstream,dag,adapter,False)
    RuntimeSourceCompiler.compile_queries_for_relation(downstream,dag,adapter,False)
    assert query_equalize(downstream.compiled_query)==query_equalize(f"""
        SELECT
                *
        FROM {downstream.quoted_dot_notation}
        WHERE id IN (1,2,3) 
        UNION (SELECT
                *
            FROM {downstream.quoted_dot_notation}
            WHERE id NOT IN (SELECT id FROM {upstream.quoted_dot_notation})
            LIMIT 100)
        """)

    assert query_equalize(upstream.compiled_query)==query_equalize(f"""
        WITH {upstream.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT * FROM 
        {upstream.quoted_dot_notation} 
            WHERE id in (SELECT id 
            FROM 
        {downstream.quoted_dot_notation}) 
        )
        ,{upstream.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
            {upstream.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS)
        ) 
        SELECT 
            * 
        FROM 
            {upstream.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} 
        UNION 
        (SELECT 
            * 
        FROM 
        {upstream.quoted_dot_notation} 
        WHERE 
            id 
        NOT IN 
            (SELECT 
                id 
            FROM 
        {downstream.quoted_dot_notation}) LIMIT 100)
        """
        )


def test_run_deps_bidirectional_exclude_outliers(stub_relation_set):
    upstream=stub_relation_set.upstream_relation
    downstream=stub_relation_set.downstream_relation
    for relation in (downstream,upstream,):
        relation.attributes=[Attribute('id',dt.INTEGER)]
        relation=stub_out_sampling(relation)
    upstream.data=pd.DataFrame([dict(id=1),dict(id=2),dict(id=3)])

    dag=nx.DiGraph()
    dag.add_edge(upstream,downstream,direction="bidirectional",remote_attribute='id',local_attribute='id')
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(upstream,dag,adapter,False)
    RuntimeSourceCompiler.compile_queries_for_relation(downstream,dag,adapter,False)
    assert query_equalize(downstream.compiled_query)==query_equalize(f"""
            SELECT
                *
            FROM {downstream.quoted_dot_notation}
            WHERE id IN (1,2,3)
    """)

    assert query_equalize(upstream.compiled_query)==query_equalize(f"""
        WITH {upstream.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
            {upstream.quoted_dot_notation} 
        WHERE 
            id 
        in (SELECT 
                id 
            FROM 
                {downstream.quoted_dot_notation}) ) 
        ,{upstream.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
            SELECT 
                * 
            FROM 
                {upstream.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {upstream.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)


def test_run_deps_directional_line_graph():
    """
        a --dir--> b --dir--> c
    """
    relation_helper = RelationTestHelper()
    relation_a = Relation(name='rel_a', **relation_helper.rand_relation_helper())
    relation_a.attributes = [Attribute('col_a',dt.INTEGER)]
    relation_a.data = pd.DataFrame({"col_a": [1, 2, 3, 4, 5,]})

    relation_b = Relation(name='rel_b', **relation_helper.rand_relation_helper())
    relation_b.attributes = [Attribute('col_b_a',dt.INTEGER), Attribute('col_b_c', dt.VARCHAR)]
    relation_b.data = pd.DataFrame({
        "col_b_a": [1, 3, 4, 4,],
        "col_b_c": ["val1", "val3", "val4", "val4",],
    })

    relation_c = Relation(name='rel_c', **relation_helper.rand_relation_helper())
    relation_c.attributes = [Attribute('col_c',dt.VARCHAR)]

    for relation in (relation_a, relation_b, relation_c,):
        relation=stub_out_sampling(relation)

    dag=nx.DiGraph()
    dag.add_edge(relation_a, relation_b, direction="directional", remote_attribute="col_a", local_attribute="col_b_a")
    dag.add_edge(relation_b, relation_c, direction="directional", remote_attribute="col_b_c", local_attribute="col_c")
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(relation_a, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_b, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_c, dag, adapter, False)
    assert query_equalize(relation_a.compiled_query) == query_equalize(f"""
        SELECT
            *
        FROM
            {relation_a.quoted_dot_notation}
        SAMPLE BERNOULLI (1500 ROWS)
    """)
    assert query_equalize(relation_b.compiled_query) == query_equalize(f"""
        WITH 
        {relation_b.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_b.quoted_dot_notation}
        WHERE col_b_a IN (1,2,3,4,5) 
        )
        ,{relation_b.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_b.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_b.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)
    assert query_equalize(relation_c.compiled_query) == query_equalize(f"""
        WITH 
        {relation_c.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_c.quoted_dot_notation}
        WHERE col_c IN ('val1','val3','val4') 
        )
        ,{relation_c.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_c.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_c.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)


def test_run_deps_bidirectional_line_graph():
    """
        a --bidir--> b --bidir--> c
    """
    relation_helper = RelationTestHelper()
    relation_a = Relation(name='rel_a', **relation_helper.rand_relation_helper())
    relation_a.attributes = [Attribute('col_a',dt.INTEGER)]
    relation_a.data = pd.DataFrame({"col_a": [1, 2, 3, 4, 5,]})

    relation_b = Relation(name='rel_b', **relation_helper.rand_relation_helper())
    relation_b.attributes = [Attribute('col_b_a',dt.INTEGER), Attribute('col_b_c', dt.VARCHAR)]
    relation_b.data = pd.DataFrame({
        "col_b_a": [1, 3, 4, 4,],
        "col_b_c": ["val1", "val3", "val4", "val4",],
    })

    relation_c = Relation(name='rel_c', **relation_helper.rand_relation_helper())
    relation_c.attributes = [Attribute('col_c',dt.VARCHAR)]

    for relation in (relation_a, relation_b, relation_c,):
        relation=stub_out_sampling(relation)

    dag=nx.DiGraph()
    dag.add_edge(relation_a, relation_b, direction="bidirectional", remote_attribute="col_a", local_attribute="col_b_a")
    dag.add_edge(relation_b, relation_c, direction="bidirectional", remote_attribute="col_b_c", local_attribute="col_c")
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(relation_a, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_b, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_c, dag, adapter, False)
    assert query_equalize(relation_a.compiled_query) == query_equalize(f"""
        WITH {relation_a.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
            {relation_a.quoted_dot_notation} 
        WHERE 
            col_a 
        in (SELECT 
                col_b_a 
            FROM 
                {relation_b.quoted_dot_notation}) ) 
        ,{relation_a.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
            SELECT 
                * 
            FROM 
                {relation_a.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_a.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)
    assert query_equalize(relation_b.compiled_query) == query_equalize(f"""
        SELECT 
            * 
        FROM 
        {relation_b.quoted_dot_notation}
        WHERE col_b_c 
        in (SELECT 
                col_c 
            FROM 
                {relation_c.quoted_dot_notation})
        AND col_b_a IN (1,2,3,4,5) 
    """)
    assert query_equalize(relation_c.compiled_query) == query_equalize(f"""
            SELECT
                *
            FROM {relation_c.quoted_dot_notation} 
            WHERE col_c IN ('val1','val3','val4')
    """)


def test_run_deps_directional_multi_deps():
    """
        a --dir--> c <--dir-- b
    """
    relation_helper = RelationTestHelper()
    relation_a = Relation(name='rel_a', **relation_helper.rand_relation_helper())
    relation_a.attributes = [Attribute('col_a',dt.INTEGER)]
    relation_a.data = pd.DataFrame({"col_a": [1, 2, 3, 4, 5,]})

    relation_b = Relation(name='rel_b', **relation_helper.rand_relation_helper())
    relation_b.attributes = [Attribute('col_b',dt.VARCHAR)]
    relation_b.data = pd.DataFrame({"col_b": ["val1", "val2", "val3", "val4", "val5",],})

    relation_c = Relation(name='rel_c', **relation_helper.rand_relation_helper())
    relation_c.attributes = [Attribute('col_c_a',dt.INTEGER), Attribute('col_c_b', dt.VARCHAR)]

    for relation in (relation_a, relation_b, relation_c,):
        relation=stub_out_sampling(relation)

    dag=nx.DiGraph()
    dag.add_edge(relation_a, relation_c, direction="directional", remote_attribute="col_a", local_attribute="col_c_a")
    dag.add_edge(relation_b, relation_c, direction="directional", remote_attribute="col_b", local_attribute="col_c_b")
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(relation_a, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_b, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_c, dag, adapter, False)
    assert query_equalize(relation_a.compiled_query) == query_equalize(f"""
        SELECT
            *
        FROM
            {relation_a.quoted_dot_notation}
        SAMPLE BERNOULLI (1500 ROWS)
    """)
    assert query_equalize(relation_b.compiled_query) == query_equalize(f"""
        SELECT
            *
        FROM
            {relation_b.quoted_dot_notation}
        SAMPLE BERNOULLI (1500 ROWS)
    """)
    assert query_equalize(relation_c.compiled_query) == query_equalize(f"""
        WITH 
        {relation_c.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_c.quoted_dot_notation}
        WHERE 
            col_c_a IN (1,2,3,4,5) 
        AND
            col_c_b IN ('val1','val2','val3','val4','val5') 
        )
        ,{relation_c.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_c.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_c.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)


def test_run_deps_bidirectional_multi_deps():
    """
        a --bidir--> c <--bidir-- b
    """
    relation_helper = RelationTestHelper()
    relation_a = Relation(name='rel_a', **relation_helper.rand_relation_helper())
    relation_a.attributes = [Attribute('col_a',dt.INTEGER)]
    relation_a.data = pd.DataFrame({"col_a": [1, 2, 3, 4, 5,]})

    relation_b = Relation(name='rel_b', **relation_helper.rand_relation_helper())
    relation_b.attributes = [Attribute('col_b',dt.VARCHAR)]
    relation_b.data = pd.DataFrame({"col_b": ["val1", "val2", "val3", "val4", "val5",],})

    relation_c = Relation(name='rel_c', **relation_helper.rand_relation_helper())
    relation_c.attributes = [Attribute('col_c_a',dt.INTEGER), Attribute('col_c_b', dt.VARCHAR)]

    for relation in (relation_a, relation_b, relation_c,):
        relation=stub_out_sampling(relation)

    dag=nx.DiGraph()
    dag.add_edge(relation_a, relation_c, direction="bidirectional", remote_attribute="col_a", local_attribute="col_c_a")
    dag.add_edge(relation_b, relation_c, direction="bidirectional", remote_attribute="col_b", local_attribute="col_c_b")
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(relation_a, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_b, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_c, dag, adapter, False)
    assert query_equalize(relation_a.compiled_query) == query_equalize(f"""
        WITH {relation_a.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
            {relation_a.quoted_dot_notation} 
        WHERE 
            col_a 
        in (SELECT 
                col_c_a 
            FROM 
                {relation_c.quoted_dot_notation}) ) 
        ,{relation_a.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
            SELECT 
                * 
            FROM 
                {relation_a.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_a.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)
    assert query_equalize(relation_b.compiled_query) == query_equalize(f"""
        WITH 
        {relation_b.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_b.quoted_dot_notation}
        WHERE 
            col_b 
        in (SELECT 
                col_c_b 
            FROM 
                {relation_c.quoted_dot_notation})
        )
        ,{relation_b.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_b.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_b.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)
    assert query_equalize(relation_c.compiled_query) == query_equalize(f"""
            SELECT
                *
            FROM {relation_c.quoted_dot_notation} 
            WHERE
                col_c_a IN (1,2,3,4,5)
            AND
                col_c_b IN ('val1','val2','val3','val4','val5')
    """)


def test_run_deps_mixed_multi_deps():
    r"""
        a --bidir--> c <--dir-- b
         \          / \
          \     bidir  dir
           \       |   |
            \      V   V
             dir-> d   e
    """
    relation_helper = RelationTestHelper()
    relation_a = Relation(name='rel_a', **relation_helper.rand_relation_helper())
    relation_a.attributes = [Attribute('col_a_c',dt.INTEGER), Attribute('col_a_d',dt.VARCHAR)]
    relation_a.data = pd.DataFrame(
        {
            "col_a_c": [1, 2, 3, 4, 5,],
            "col_a_d": ["var_a_1", "var_a_2", "var_a_3", "var_a_1", "var_a_2"],
        }
    )
    relation_b = Relation(name='rel_b', **relation_helper.rand_relation_helper())
    relation_b.attributes = [Attribute('col_b_c',dt.VARCHAR)]
    relation_b.data = pd.DataFrame({"col_b_c": ["val1", "val2", "val3", "val4", "val5",],})

    relation_c = Relation(name='rel_c', **relation_helper.rand_relation_helper())
    relation_c.attributes = [Attribute('col_c_ae',dt.INTEGER), Attribute('col_c_bd', dt.VARCHAR)]
    relation_c.data = pd.DataFrame(
        {
            "col_c_ae": [1, 1, 2, 2, 5, 5, 5,],
            "col_c_bd": ["val1", "val1", "val2", "val2", "val5", "val5", "val5",]
        }
    )

    relation_d = Relation(name='rel_d', **relation_helper.rand_relation_helper())
    relation_d.attributes = [Attribute('col_d_a',dt.INTEGER), Attribute('col_d_c',dt.INTEGER)]

    relation_e = Relation(name='rel_e', **relation_helper.rand_relation_helper())
    relation_e.attributes = [Attribute('col_e_c',dt.INTEGER)]

    for relation in (relation_a, relation_b, relation_c, relation_d, relation_e,):
        relation=stub_out_sampling(relation)

    dag=nx.DiGraph()
    dag.add_edge(relation_a, relation_c, direction="bidirectional", remote_attribute="col_a_c", local_attribute="col_c_ae")
    dag.add_edge(relation_a, relation_d, direction="directional", remote_attribute="col_a_d", local_attribute="col_d_a")
    dag.add_edge(relation_b, relation_c, direction="directional", remote_attribute="col_b_c", local_attribute="col_c_bd")
    dag.add_edge(relation_c, relation_d, direction="bidirectional", remote_attribute="col_c_bd", local_attribute="col_d_c")
    dag.add_edge(relation_c, relation_e, direction="directional", remote_attribute="col_c_ae", local_attribute="col_e_c")
    adapter=SnowflakeAdapter()
    RuntimeSourceCompiler.compile_queries_for_relation(relation_a, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_b, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_c, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_d, dag, adapter, False)
    RuntimeSourceCompiler.compile_queries_for_relation(relation_e, dag, adapter, False)
    assert query_equalize(relation_a.compiled_query) == query_equalize(f"""
        WITH {relation_a.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
            {relation_a.quoted_dot_notation} 
        WHERE 
            col_a_c 
        in (SELECT 
                col_c_ae 
            FROM 
                {relation_c.quoted_dot_notation}) ) 
        ,{relation_a.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
            SELECT 
                * 
            FROM 
                {relation_a.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_a.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)
    assert query_equalize(relation_b.compiled_query) == query_equalize(f"""
        SELECT
            *
        FROM
            {relation_b.quoted_dot_notation}
        SAMPLE BERNOULLI (1500 ROWS)
    """)
    assert query_equalize(relation_c.compiled_query) == query_equalize(f"""
        SELECT 
            * 
        FROM 
            {relation_c.quoted_dot_notation} 
        WHERE 
            col_c_bd 
        in (SELECT 
                col_d_c 
            FROM 
                {relation_d.quoted_dot_notation})
        AND
            col_c_ae IN (1,2,3,4,5)
        AND
            col_c_bd IN ('val1','val2','val3','val4','val5')
    """)
    assert query_equalize(relation_d.compiled_query) == query_equalize(f"""
        SELECT 
            * 
        FROM 
            {relation_d.quoted_dot_notation}
        WHERE 
            col_d_a IN ('var_a_1','var_a_2','var_a_3') 
        AND
            col_d_c IN ('val1','val2','val5') 
    """)
    assert query_equalize(relation_e.compiled_query) == query_equalize(f"""
        WITH 
        {relation_e.scoped_cte('SNOWSHU_FINAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_e.quoted_dot_notation}
        WHERE 
            col_e_c IN (1,2,5) 
        )
        ,{relation_e.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')} AS ( 
        SELECT 
            * 
        FROM 
        {relation_e.scoped_cte('SNOWSHU_FINAL_SAMPLE')} SAMPLE BERNOULLI (1500 ROWS) 
        ) 
        SELECT 
            * 
        FROM 
        {relation_e.scoped_cte('SNOWSHU_DIRECTIONAL_SAMPLE')}
    """)