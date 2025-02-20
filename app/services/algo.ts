import { nanoid } from "nanoid";
import sha256 from "crypto-js/sha256";


interface Connection {
    isSource: boolean;
    nodes: Set<string>;
  }
  interface ConnectionWithType {
    isSource: boolean;
    nodes: string[];
    type: string;
  }
  type EdgeTypeToConnectionMapping = Map<string, Connection>;
  const map = new Map<string, EdgeTypeToConnectionMapping>();
  
  function getNodeToConnectionsMap(annotation: any) {
    const map = new Map<string, EdgeTypeToConnectionMapping>();
  
    function addToMap(
      edge: (typeof annotation.edges)[number],
      node: "source" | "target",
    ) {
      let connections = map.get(edge.data[node]);
      let con = connections?.get(edge.data.label);
      if (!connections) connections = new Map();
      if (!con) con = { isSource: node == "source", nodes: new Set() };
      con.nodes.add(node == "source" ? edge.data.target : edge.data.source);
      connections.set(edge.data.label, con);
      map.set(edge.data[node], connections);
    }
  
    annotation.edges.forEach((edge) => {
      addToMap(edge, "source");
      addToMap(edge, "target");
    });
  
    return map;
  }
  
  function collapseNodes(annotation: any) {
    const map = getNodeToConnectionsMap(annotation);
  
    const mapString: {
      [hash: string]: { connections: ConnectionWithType[]; nodes: string[] };
    } = {};
    const ids = new Map<string, string>();
    map.forEach((connections, nodeId) => {
      const connectionsArray: ConnectionWithType[] = [];
      connections.forEach((connection, edgeLabel) => {
        const nodes: string[] = [];
        connection.nodes.forEach((n) => nodes.push(n));
        connectionsArray.push({
          nodes: nodes.sort(),
          type: edgeLabel,
          isSource: connection.isSource,
        });
      });
      const connectionsHash = sha256(
        JSON.stringify(
          connectionsArray.sort((a, b) => {
            return JSON.stringify(a) > JSON.stringify(b) ? 1 : 2;
          }),
        ),
      );
      if (mapString[connectionsHash]) {
        mapString[connectionsHash].nodes.push(nodeId);
      } else {
        mapString[connectionsHash] = {
          connections: connectionsArray,
          nodes: [nodeId],
        };
      }
      ids.set(nodeId, connectionsHash);
    });
  
    // now that we have the group of nodes, we can construct a new collpased graph
    const newGraph: { edges: any; nodes: any } = {
      edges: [],
      nodes: [],
    };
  
    // for group key
    Object.keys(mapString).map((k) => {
      // get the group
      const group = mapString[k];
      // and create a new node for it
      // the hash serves as its key
      const node = annotation.nodes.find((n) => group.nodes.includes(n.data.id));
  
      // since the nodes are all of the same type, we can take the type of the first node
      // in the list
      const type = node!.data.type;
      const name =
        group.nodes.length === 1
          ? node!.data.name
          : `${group.nodes.length} ${node!.data.type} nodes`;
      const newNode = {
        data: {
          id: k,
          type,
          name,
          nodes: group.nodes,
        },
      };
  
      newGraph.nodes.push(newNode);
  
      const added = new Set();
  
      // for each connection in the group, create edges that point to/from the new node we just
      // created. we only add edges for connections that specify a source, to avoid duplicate edges.
      // every edge has a source and target, so the edges that specify a target in this group, will
      // specify a source in another group and they will be added then.
      const edges: any[] = [];
      group.connections
        .filter((c) => c.isSource)
        .map((c) => {
          c.nodes.forEach((n) => {
            // get the ID of the node this compound node is connected to
            const otherNodeID = ids.get(n);
            const edge = {
              data: {
                id: nanoid(),
                label: c.type,
                target: c.isSource ? otherNodeID : k,
                source: c.isSource ? k : otherNodeID,
              },
            };
  
            if (
              [edge.data.source, edge.data.target].includes("12 pathway nodes")
            ) {
              const key = `${edge.data.label}${edge.data.source}${edge.data.target}`;
            }
  
            const key = `${edge.data.label}${edge.data.source}${edge.data.target}`;
            if (added.has(key)) return;
            added.add(key);
            edges.push(edge);
          });
        });
  
      newGraph.edges.push(...edges);
    });
  
    return newGraph;
  }
  const annotation={'nodes': [{'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001901152', 'type': 'exon', 'name': 'exon ense00001901152'}}, {'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001218547', 'type': 'exon', 'name': 'exon ense00001218547'}}, {'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001477549', 'type': 'exon', 'name': 'exon ense00001477549'}}, {'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000659009', 'type': 'exon', 'name': 'exon ense00000659009'}}, {'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000659008', 'type': 'exon', 'name': 'exon ense00000659008'}}, {'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001598137', 'type': 'exon', 'name': 'exon ense00001598137'}}, {'data': {'id': 'transcript enst00000353224', 'type': 'transcript', 'name': 'PAK5-201'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000859083', 'type': 'exon', 'name': 'exon ense00000859083'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001218547', 'type': 'exon', 'name': 'exon ense00001218547'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001477549', 'type': 'exon', 'name': 'exon ense00001477549'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000659009', 'type': 'exon', 'name': 'exon ense00000659009'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000659008', 'type': 'exon', 'name': 'exon ense00000659008'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001598137', 'type': 'exon', 'name': 'exon ense00001598137'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000859083', 'type': 'exon', 'name': 'exon ense00000859083'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001477490', 'type': 'exon', 'name': 'exon ense00001477490'}}, {'data': {'id': 'transcript enst00000378423', 'type': 'transcript', 'name': 'PAK5-202'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001477489', 'type': 'exon', 'name': 'exon ense00001477489'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001218547', 'type': 'exon', 'name': 'exon ense00001218547'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001477549', 'type': 'exon', 'name': 'exon ense00001477549'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000659009', 'type': 'exon', 'name': 'exon ense00000659009'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000659008', 'type': 'exon', 'name': 'exon ense00000659008'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001598137', 'type': 'exon', 'name': 'exon ense00001598137'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00000859083', 'type': 'exon', 'name': 'exon ense00000859083'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001899879', 'type': 'exon', 'name': 'exon ense00001899879'}}, {'data': {'id': 'transcript enst00000378429', 'type': 'transcript', 'name': 'PAK5-203'}}, {'data': {'id': 'gene ensg00000101349', 'type': 'gene', 'name': 'PAK5'}}, {'data': {'id': 'exon ense00001403884', 'type': 'exon', 'name': 'exon ense00001403884'}}, {'data': {'id': 'transcript enst00000657954', 'type': 'transcript', 'name': 'ENST00000657954'}}, {'data': {'id': 'gene ensg00000286740', 'type': 'gene', 'name': 'ENSG00000286740'}}, {'data': {'id': 'exon ense00003875467', 'type': 'exon', 'name': 'exon ense00003875467'}}, {'data': {'id': 'transcript enst00000657954', 'type': 'transcript', 'name': 'ENST00000657954'}}, {'data': {'id': 'gene ensg00000286740', 'type': 'gene', 'name': 'ENSG00000286740'}}, {'data': {'id': 'exon ense00003883630', 'type': 'exon', 'name': 'exon ense00003883630'}}, {'data': {'id': 'transcript enst00000428769', 'type': 'transcript', 'name': 'ENST00000428769'}}, {'data': {'id': 'gene ensg00000232738', 'type': 'gene', 'name': 'ENSG00000232738'}}, {'data': {'id': 'exon ense00001673273', 'type': 'exon', 'name': 'exon ense00001673273'}}, {'data': {'id': 'transcript enst00000428769', 'type': 'transcript', 'name': 'ENST00000428769'}}, {'data': {'id': 'gene ensg00000232738', 'type': 'gene', 'name': 'ENSG00000232738'}}, {'data': {'id': 'exon ense00001682897', 'type': 'exon', 'name': 'exon ense00001682897'}}, {'data': {'id': 'transcript enst00000656748', 'type': 'transcript', 'name': 'ENST00000656748'}}, {'data': {'id': 'gene ensg00000286470', 'type': 'gene', 'name': 'ENSG00000286470'}}, {'data': {'id': 'exon ense00003863098', 'type': 'exon', 'name': 'exon ense00003863098'}}, {'data': {'id': 'transcript enst00000656748', 'type': 'transcript', 'name': 'ENST00000656748'}}, {'data': {'id': 'gene ensg00000286470', 'type': 'gene', 'name': 'ENSG00000286470'}}, {'data': {'id': 'exon ense00003868250', 'type': 'exon', 'name': 'exon ense00003868250'}}, {'data': {'id': 'transcript enst00000656748', 'type': 'transcript', 'name': 'ENST00000656748'}}, {'data': {'id': 'gene ensg00000286470', 'type': 'gene', 'name': 'ENSG00000286470'}}, {'data': {'id': 'exon ense00003880241', 'type': 'exon', 'name': 'exon ense00003880241'}}, {'data': {'id': 'transcript enst00000449270', 'type': 'transcript', 'name': 'PARAL1-201'}}, {'data': {'id': 'gene ensg00000243961', 'type': 'gene', 'name': 'PARAL1'}}, {'data': {'id': 'exon ense00001736075', 'type': 'exon', 'name': 'exon ense00001736075'}}, {'data': {'id': 'transcript enst00000449270', 'type': 'transcript', 'name': 'PARAL1-201'}}, {'data': {'id': 'gene ensg00000243961', 'type': 'gene', 'name': 'PARAL1'}}, {'data': {'id': 'exon ense00001727795', 'type': 'exon', 'name': 'exon ense00001727795'}}, {'data': {'id': 'transcript enst00000437504', 'type': 'transcript', 'name': 'ANKEF1-203'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001639435', 'type': 'exon', 'name': 'exon ense00001639435'}}, {'data': {'id': 'transcript enst00000437504', 'type': 'transcript', 'name': 'ANKEF1-203'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001755953', 'type': 'exon', 'name': 'exon ense00001755953'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001477365', 'type': 'exon', 'name': 'exon ense00001477365'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001477354', 'type': 'exon', 'name': 'exon ense00001477354'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003654766', 'type': 'exon', 'name': 'exon ense00003654766'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003520744', 'type': 'exon', 'name': 'exon ense00003520744'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003652008', 'type': 'exon', 'name': 'exon ense00003652008'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003621228', 'type': 'exon', 'name': 'exon ense00003621228'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003682380', 'type': 'exon', 'name': 'exon ense00003682380'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003621601', 'type': 'exon', 'name': 'exon ense00003621601'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003571338', 'type': 'exon', 'name': 'exon ense00003571338'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003531424', 'type': 'exon', 'name': 'exon ense00003531424'}}, {'data': {'id': 'transcript enst00000378392', 'type': 'transcript', 'name': 'ANKEF1-202'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001888001', 'type': 'exon', 'name': 'exon ense00001888001'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003654766', 'type': 'exon', 'name': 'exon ense00003654766'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003520744', 'type': 'exon', 'name': 'exon ense00003520744'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003652008', 'type': 'exon', 'name': 'exon ense00003652008'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003621228', 'type': 'exon', 'name': 'exon ense00003621228'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003682380', 'type': 'exon', 'name': 'exon ense00003682380'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003621601', 'type': 'exon', 'name': 'exon ense00003621601'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003571338', 'type': 'exon', 'name': 'exon ense00003571338'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003531424', 'type': 'exon', 'name': 'exon ense00003531424'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001888001', 'type': 'exon', 'name': 'exon ense00001888001'}}, {'data': {'id': 'transcript enst00000378380', 'type': 'transcript', 'name': 'ANKEF1-201'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001175405', 'type': 'exon', 'name': 'exon ense00001175405'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001946515', 'type': 'exon', 'name': 'exon ense00001946515'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003479326', 'type': 'exon', 'name': 'exon ense00003479326'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001882823', 'type': 'exon', 'name': 'exon ense00001882823'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003474270', 'type': 'exon', 'name': 'exon ense00003474270'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003590148', 'type': 'exon', 'name': 'exon ense00003590148'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003473553', 'type': 'exon', 'name': 'exon ense00003473553'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003494486', 'type': 'exon', 'name': 'exon ense00003494486'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003623880', 'type': 'exon', 'name': 'exon ense00003623880'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003674131', 'type': 'exon', 'name': 'exon ense00003674131'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00003690857', 'type': 'exon', 'name': 'exon ense00003690857'}}, {'data': {'id': 'transcript enst00000488991', 'type': 'transcript', 'name': 'ANKEF1-204'}}, {'data': {'id': 'gene ensg00000132623', 'type': 'gene', 'name': 'ANKEF1'}}, {'data': {'id': 'exon ense00001952776', 'type': 'exon', 'name': 'exon ense00001952776'}}, {'data': {'id': 'transcript enst00000655841', 'type': 'transcript', 'name': 'SNAP25-AS1-210'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003878659', 'type': 'exon', 'name': 'exon ense00003878659'}}, {'data': {'id': 'transcript enst00000655841', 'type': 'transcript', 'name': 'SNAP25-AS1-210'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003867187', 'type': 'exon', 'name': 'exon ense00003867187'}}, {'data': {'id': 'transcript enst00000658520', 'type': 'transcript', 'name': 'SNAP25-AS1-213'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003888198', 'type': 'exon', 'name': 'exon ense00003888198'}}, {'data': {'id': 'transcript enst00000658520', 'type': 'transcript', 'name': 'SNAP25-AS1-213'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003883120', 'type': 'exon', 'name': 'exon ense00003883120'}}, {'data': {'id': 'transcript enst00000658520', 'type': 'transcript', 'name': 'SNAP25-AS1-213'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003861280', 'type': 'exon', 'name': 'exon ense00003861280'}}, {'data': {'id': 'transcript enst00000658520', 'type': 'transcript', 'name': 'SNAP25-AS1-213'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003871236', 'type': 'exon', 'name': 'exon ense00003871236'}}, {'data': {'id': 'transcript enst00000658520', 'type': 'transcript', 'name': 'SNAP25-AS1-213'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003865888', 'type': 'exon', 'name': 'exon ense00003865888'}}, {'data': {'id': 'transcript enst00000603245', 'type': 'transcript', 'name': 'SNAP25-AS1-206'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003671633', 'type': 'exon', 'name': 'exon ense00003671633'}}, {'data': {'id': 'transcript enst00000603245', 'type': 'transcript', 'name': 'SNAP25-AS1-206'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003521230', 'type': 'exon', 'name': 'exon ense00003521230'}}, {'data': {'id': 'transcript enst00000661614', 'type': 'transcript', 'name': 'SNAP25-AS1-216'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003535996', 'type': 'exon', 'name': 'exon ense00003535996'}}, {'data': {'id': 'transcript enst00000661614', 'type': 'transcript', 'name': 'SNAP25-AS1-216'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001681685', 'type': 'exon', 'name': 'exon ense00001681685'}}, {'data': {'id': 'transcript enst00000661614', 'type': 'transcript', 'name': 'SNAP25-AS1-216'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001728322', 'type': 'exon', 'name': 'exon ense00001728322'}}, {'data': {'id': 'transcript enst00000661614', 'type': 'transcript', 'name': 'SNAP25-AS1-216'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001794719', 'type': 'exon', 'name': 'exon ense00001794719'}}, {'data': {'id': 'transcript enst00000661614', 'type': 'transcript', 'name': 'SNAP25-AS1-216'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003881707', 'type': 'exon', 'name': 'exon ense00003881707'}}, {'data': {'id': 'transcript enst00000663466', 'type': 'transcript', 'name': 'SNAP25-AS1-218'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001681685', 'type': 'exon', 'name': 'exon ense00001681685'}}, {'data': {'id': 'transcript enst00000663466', 'type': 'transcript', 'name': 'SNAP25-AS1-218'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001728322', 'type': 'exon', 'name': 'exon ense00001728322'}}, {'data': {'id': 'transcript enst00000663466', 'type': 'transcript', 'name': 'SNAP25-AS1-218'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001794719', 'type': 'exon', 'name': 'exon ense00001794719'}}, {'data': {'id': 'transcript enst00000663466', 'type': 'transcript', 'name': 'SNAP25-AS1-218'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003862134', 'type': 'exon', 'name': 'exon ense00003862134'}}, {'data': {'id': 'transcript enst00000663466', 'type': 'transcript', 'name': 'SNAP25-AS1-218'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003869384', 'type': 'exon', 'name': 'exon ense00003869384'}}, {'data': {'id': 'transcript enst00000663466', 'type': 'transcript', 'name': 'SNAP25-AS1-218'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003868966', 'type': 'exon', 'name': 'exon ense00003868966'}}, {'data': {'id': 'transcript enst00000670580', 'type': 'transcript', 'name': 'SNAP25-AS1-222'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001681685', 'type': 'exon', 'name': 'exon ense00001681685'}}, {'data': {'id': 'transcript enst00000670580', 'type': 'transcript', 'name': 'SNAP25-AS1-222'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001728322', 'type': 'exon', 'name': 'exon ense00001728322'}}, {'data': {'id': 'transcript enst00000670580', 'type': 'transcript', 'name': 'SNAP25-AS1-222'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001794719', 'type': 'exon', 'name': 'exon ense00001794719'}}, {'data': {'id': 'transcript enst00000670580', 'type': 'transcript', 'name': 'SNAP25-AS1-222'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003856118', 'type': 'exon', 'name': 'exon ense00003856118'}}, {'data': {'id': 'transcript enst00000670580', 'type': 'transcript', 'name': 'SNAP25-AS1-222'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003659605', 'type': 'exon', 'name': 'exon ense00003659605'}}, {'data': {'id': 'transcript enst00000670580', 'type': 'transcript', 'name': 'SNAP25-AS1-222'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003880110', 'type': 'exon', 'name': 'exon ense00003880110'}}, {'data': {'id': 'transcript enst00000664172', 'type': 'transcript', 'name': 'SNAP25-AS1-219'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001681685', 'type': 'exon', 'name': 'exon ense00001681685'}}, {'data': {'id': 'transcript enst00000664172', 'type': 'transcript', 'name': 'SNAP25-AS1-219'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001728322', 'type': 'exon', 'name': 'exon ense00001728322'}}, {'data': {'id': 'transcript enst00000664172', 'type': 'transcript', 'name': 'SNAP25-AS1-219'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001794719', 'type': 'exon', 'name': 'exon ense00001794719'}}, {'data': {'id': 'transcript enst00000664172', 'type': 'transcript', 'name': 'SNAP25-AS1-219'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003876205', 'type': 'exon', 'name': 'exon ense00003876205'}}, {'data': {'id': 'transcript enst00000664172', 'type': 'transcript', 'name': 'SNAP25-AS1-219'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003877026', 'type': 'exon', 'name': 'exon ense00003877026'}}, {'data': {'id': 'transcript enst00000664172', 'type': 'transcript', 'name': 'SNAP25-AS1-219'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00003541461', 'type': 'exon', 'name': 'exon ense00003541461'}}, {'data': {'id': 'transcript enst00000658443', 'type': 'transcript', 'name': 'SNAP25-AS1-212'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001681685', 'type': 'exon', 'name': 'exon ense00001681685'}}, {'data': {'id': 'transcript enst00000658443', 'type': 'transcript', 'name': 'SNAP25-AS1-212'}}, {'data': {'id': 'gene ensg00000227906', 'type': 'gene', 'name': 'SNAP25-AS1'}}, {'data': {'id': 'exon ense00001728322', 'type': 'exon', 'name': 'exon ense00001728322'}}], 'edges': [{'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000101349', 'target': 'transcript enst00000353224'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00001901152'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00001218547'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00001477549'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00000659009'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00000659008'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00001598137'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000353224', 'target': 'exon ense00000859083'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000101349', 'target': 'transcript enst00000378423'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00001218547'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00001477549'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00000659009'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00000659008'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00001598137'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00000859083'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00001477490'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378423', 'target': 'exon ense00001477489'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000101349', 'target': 'transcript enst00000378429'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00001218547'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00001477549'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00000659009'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00000659008'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00001598137'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00000859083'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00001899879'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378429', 'target': 'exon ense00001403884'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000286740', 'target': 'transcript enst00000657954'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000657954', 'target': 'exon ense00003875467'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000657954', 'target': 'exon ense00003883630'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000232738', 'target': 'transcript enst00000428769'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000428769', 'target': 'exon ense00001673273'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000428769', 'target': 'exon ense00001682897'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000286470', 'target': 'transcript enst00000656748'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000656748', 'target': 'exon ense00003863098'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000656748', 'target': 'exon ense00003868250'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000656748', 'target': 'exon ense00003880241'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000243961', 'target': 'transcript enst00000449270'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000449270', 'target': 'exon ense00001736075'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000449270', 'target': 'exon ense00001727795'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000132623', 'target': 'transcript enst00000437504'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000437504', 'target': 'exon ense00001639435'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000437504', 'target': 'exon ense00001755953'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000132623', 'target': 'transcript enst00000378392'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00001477365'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00001477354'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003654766'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003520744'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003652008'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003621228'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003682380'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003621601'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003571338'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00003531424'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378392', 'target': 'exon ense00001888001'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000132623', 'target': 'transcript enst00000378380'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003654766'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003520744'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003652008'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003621228'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003682380'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003621601'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003571338'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00003531424'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00001888001'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000378380', 'target': 'exon ense00001175405'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000132623', 'target': 'transcript enst00000488991'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00001946515'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003479326'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00001882823'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003474270'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003590148'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003473553'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003494486'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003623880'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003674131'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00003690857'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000488991', 'target': 'exon ense00001952776'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000655841'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000655841', 'target': 'exon ense00003878659'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000655841', 'target': 'exon ense00003867187'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000658520'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658520', 'target': 'exon ense00003888198'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658520', 'target': 'exon ense00003883120'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658520', 'target': 'exon ense00003861280'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658520', 'target': 'exon ense00003871236'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658520', 'target': 'exon ense00003865888'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000603245'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000603245', 'target': 'exon ense00003671633'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000603245', 'target': 'exon ense00003521230'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000661614'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000661614', 'target': 'exon ense00003535996'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000661614', 'target': 'exon ense00001681685'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000661614', 'target': 'exon ense00001728322'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000661614', 'target': 'exon ense00001794719'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000661614', 'target': 'exon ense00003881707'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000663466'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000663466', 'target': 'exon ense00001681685'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000663466', 'target': 'exon ense00001728322'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000663466', 'target': 'exon ense00001794719'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000663466', 'target': 'exon ense00003862134'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000663466', 'target': 'exon ense00003869384'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000663466', 'target': 'exon ense00003868966'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000670580'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000670580', 'target': 'exon ense00001681685'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000670580', 'target': 'exon ense00001728322'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000670580', 'target': 'exon ense00001794719'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000670580', 'target': 'exon ense00003856118'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000670580', 'target': 'exon ense00003659605'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000670580', 'target': 'exon ense00003880110'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000664172'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000664172', 'target': 'exon ense00001681685'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000664172', 'target': 'exon ense00001728322'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000664172', 'target': 'exon ense00001794719'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000664172', 'target': 'exon ense00003876205'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000664172', 'target': 'exon ense00003877026'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000664172', 'target': 'exon ense00003541461'}}, {'data': {'id': 'gene_transcribed_to_transcript', 'label': 'transcribed_to', 'source': 'gene ensg00000227906', 'target': 'transcript enst00000658443'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658443', 'target': 'exon ense00001681685'}}, {'data': {'id': 'transcript_includes_exon', 'label': 'includes', 'source': 'transcript enst00000658443', 'target': 'exon ense00001728322'}}], 'node_count': 713, 'edge_count': 1054, 'node_count_by_label': [{'count': 184, 'label': 'transcript'}, {'count': 479, 'label': 'exon'}, {'count': 50, 'label': 'gene'}], 'edge_count_by_label': [{'count': 184, 'relationship_type': 'transcribed_to'}, {'count': 870, 'relationship_type': 'includes'}]}
  
  function groupIntoParents(annotation: any) {
    /*
    map maps a node with its connected nodes. it also holds the 
    edge label for future reference. 
      {
        igf1: {
          'ege_type': {
            nodes: ['IGF1-206', 'IGF1-203', ...],
            isSource: false
          },
        }
      
      }
    */
    const map = getNodeToConnectionsMap(annotation);
  
    /*
      parentMap is a mapping created by filtering out irrelevant entries from commonSourceMapping
      (such as groups that can't be grouped because they just contain one node). It maps the IDs
      of the target nodes with the an object that specifies their count, the source node, the edge
      label and the Id of the parent node that will be created for this group.
  
      'exon ense00001829249,exon ense00001917080' => {
        count: 2,
        node: 'transcript enst00000481539',
        label: 'includes',
        id: 'aMiuScFWOW',
        isSource: true
    }
    */
    const parentMap = new Map<
      string,
      {
        id: string;
        node: string;
        label: string;
        count: number;
        isSource: boolean;
      }
    >();
  
    map.forEach((value, nodeId) => {
      // value is a map of edge type to nodes
      value.forEach((record, edgeType) => {
        if (record.nodes.size < 2) return;
        const key = Array.from(record.nodes).sort().join(",");
  
        if (!parentMap.has(key)) {
          parentMap.set(key, {
            id: nanoid(),
            node: nodeId,
            label: edgeType,
            count: record.nodes.size,
            isSource: record.isSource,
          });
        }
      });
    });
  
    /*
    We only want to group together nodes that have the same exact incoming edges. so two keys in the parent map should either be exactly the same, one should be a subset of the other or they shouldnt contain common node IDs.
    */
    const keys: string[] = [...parentMap.keys()];
    const invalidGroups = keys.filter((k) => {
      const parentK = parentMap.get(k);
      return keys.some((a) => {
        const parentA = parentMap.get(a);
        return (
          a !== k &&
          parentA?.isSource == parentK?.isSource &&
          parentA?.count! > parentK?.count! &&
          k.split(",").some((b: string) => a.includes(b))
        );
      });
    });
  
    /*
    Every key that doesnt form a valid grouping is removed from the parentMap.
    */
    invalidGroups.forEach((k) => parentMap.delete(k));
  
    /*
    the "parents" map contains the IDs of the new parent nodes to be added.
    */
    const parents = new Set();
    const groupedNodes = new Map<
      string,
      { data: { id: string; type: string; name: string; parent?: string } }[]
    >();
    annotation.nodes.map((n) => {
      let nodeCount = 0;
      for (const [key, parent] of parentMap.entries()) {
        if (key.includes(n.data.id) && parent.count > nodeCount) {
          (n.data as any).parent = parent.id; // Assign the parent field
          nodeCount = parent.count;
        }
      }
      const parentId = (n.data as any).parent;
      if (parentId) {
        parents.add(parentId);
        groupedNodes.set(parentId, [...(groupedNodes.get(parentId) || []), n]);
      }
    });
  
    /*
    since each node decides which group it wants to belong to, there might be a case where
    a group only contains one node. we do not want to have a compount node with a single node
    inside it, so we remove those groups. 
    */
    for (const [key, entry] of groupedNodes.entries()) {
      if (entry.length < 2) {
        parents.delete(key);
        entry.map((n) => (n.data.parent = ""));
      }
    }
  
    parents.forEach((p) => {
      annotation.nodes.push({
        data: { id: p as string, type: "parent", name: p as string },
      });
    });
  
    /*
    remove all edges that point to nodes that have just been assigned parents.
    */
    const edges = annotation.edges.filter((e) => {
      const { label, source, target } = e.data;
      for (const [key, parent] of parentMap.entries()) {
        if (!parents.has(parent.id)) continue;
        const edgeKey = parent.isSource ? target : source;
        const parentNode = parent.isSource ? source : target;
  
        if (
          key.includes(edgeKey) &&
          parent.node == parentNode &&
          parent.label == label
        )
          return false;
      }
      return true;
    });
  
    /*
    add new edges that point to the newly created parents instead.
    */
    for (const [key, parent] of parentMap.entries()) {
      if (!parents.has(parent.id)) continue;
  
      const [source, target] = parent.isSource
        ? [parent.node, parent.id]
        : [parent.id, parent.node];
  
      const e = {
        data: {
          id: nanoid(),
          source,
          target,
          label: parent.label,
        },
      };
      edges.push(e);
    }
  
    annotation.edges = edges;
  }

  