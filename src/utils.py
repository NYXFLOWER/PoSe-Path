from sklearn import metrics
from itertools import combinations
import matplotlib.pyplot as plt
import networkx as nx
import scipy.sparse as sp
import numpy as np
import torch


def remove_bidirection(edge_index, edge_type):
    mask = edge_index[0] > edge_index[1]
    keep_set = mask.nonzero().view(-1)

    if edge_type is None:
        return edge_index[:, keep_set]
    else:
        return edge_index[:, keep_set], edge_type[keep_set]


def to_bidirection(edge_index, edge_type=None):
    tmp = edge_index.clone()
    tmp[0, :], tmp[1, :] = edge_index[1, :], edge_index[0, :]
    if edge_type is None:
        return torch.cat([edge_index, tmp], dim=1)
    else:
        return torch.cat([edge_index, tmp], dim=1), torch.cat([edge_type, edge_type])


def get_range_list(edge_list):
    tmp = []
    s = 0
    for i in edge_list:
        tmp.append((s, s + i.shape[1]))
        s += i.shape[1]
    return torch.tensor(tmp)


def process_edges(raw_edge_list, p=0.9):
    train_list = []
    test_list = []
    train_label_list = []
    test_label_list = []

    for i, idx in enumerate(raw_edge_list):
        train_mask = np.random.binomial(1, p, idx.shape[1])
        test_mask = 1 - train_mask
        train_set = train_mask.nonzero()[0]
        test_set = test_mask.nonzero()[0]

        train_list.append(idx[:, train_set])
        test_list.append(idx[:, test_set])

        train_label_list.append(torch.ones(2 * train_set.size, dtype=torch.long) * i)
        test_label_list.append(torch.ones(2 * test_set.size, dtype=torch.long) * i)

    train_list = [to_bidirection(idx) for idx in train_list]
    test_list = [to_bidirection(idx) for idx in test_list]

    train_range = get_range_list(train_list)
    test_range = get_range_list(test_list)

    train_edge_idx = torch.cat(train_list, dim=1)
    test_edge_idx = torch.cat(test_list, dim=1)

    train_et = torch.cat(train_label_list)
    test_et = torch.cat(test_label_list)

    return train_edge_idx, train_et, train_range, test_edge_idx, test_et, test_range


def sparse_id(n):
    idx = [[i for i in range(n)], [i for i in range(n)]]
    val = [1 for i in range(n)]
    i = torch.LongTensor(idx)
    v = torch.FloatTensor(val)
    shape = (n, n)

    return torch.sparse.FloatTensor(i, v, torch.Size(shape))


def dense_id(n):
    idx = [i for i in range(n)]
    val = [1 for _ in range(n)]
    out = sp.coo_matrix((val, (idx, idx)), shape=(n, n), dtype=float)

    return torch.Tensor(out.todense())


def auprc_auroc_ap(target_tensor, score_tensor):
    y = target_tensor.detach().cpu().numpy()
    pred = score_tensor.detach().cpu().numpy()
    auroc, ap = metrics.roc_auc_score(y, pred), metrics.average_precision_score(y, pred)
    y, xx, _ = metrics.ranking.precision_recall_curve(y, pred)
    auprc = metrics.ranking.auc(xx, y)

    return auprc, auroc, ap


def uniform(size, tensor):
    bound = 1.0 / np.sqrt(size)
    if tensor is not None:
        tensor.data.uniform_(-bound, bound)


def dict_ep_to_nparray(out_dict, epoch):
    out = np.zeros(shape=(3, epoch))
    for ep, [prc, roc, ap] in out_dict.items():
        out[0, ep] = prc
        out[1, ep] = roc
        out[2, ep] = ap
    return out


def get_indices_mask(indices, in_indices):
    d = indices.shape[-1]
    isin = np.isin(indices, in_indices).reshape(-1, d)
    mask = isin.all(axis=0)
    return torch.from_numpy(mask)


def get_edge_index_from_coo(mat, bidirection):
    if bidirection:
        mask = mat.row > mat.col
        half = np.concatenate([mat.row[mask].reshape(1, -1), mat.col[mask].reshape(1, -1)], axis=0)
        full = np.concatenate([half, half[[1, 0], :]], axis=1)
        return torch.from_numpy(full.astype(np.int64))
    else:
        tmp = np.concatenate([mat.row.reshape(1, -1), mat.col.reshape(1, -1)], axis=0)
        return torch.from_numpy(tmp.astype(np.int64))


def visualize_graph(pp_idx, pp_weight, pd_idx, pd_weight, pp_adj, out_path,
                    protein_name_dict=None, drug_name_dict=None):
    '''
    :param pp_idx: integer tensor of the shape (2, n_pp_edges)
    :param pp_weight: float tensor of the shape (1, n_pp_edges), values within (0,1)
    :param pd_idx: integer tensor of the shape (2, n_pd_edges)
    :param pd_weight: float tensor of the shape (1, n_pd_edges), values within (0,1)
    :param protein_name_dict: store elements {protein_index -> protein name}
    :param drug_name_dict: store elements {drug_index -> drug name}

    1. use different color for pp and pd edges
    2. annotate the weight of each edge near the edge (or annotate with the tranparentness of edges for each edge)
    3. annotate the name of each node near the node, if name_dict=None, then annotate with node's index
    '''
    G = nx.Graph()
    pp_edge, pd_edge, pp_link = [], [], []
    p_node, d_node = set(), set()

    if not protein_name_dict:
        tmp = set(pp_idx.flatten()) | set(pd_idx[0])
        protein_name_dict = {i: 'p-'+str(i) for i in tmp}
    if not drug_name_dict:
        drug_name_dict = {i: 'd-'+str(i) for i in set(pd_idx[1])}

    # add pp edges
    for e in zip(pp_idx.T, pp_weight.T):
        t1, t2 = protein_name_dict[e[0][0]], protein_name_dict[e[0][1]]
        G.add_edge(t1, t2, weights=e[1])
        pp_edge.append((t1, t2))
        p_node.update([t1, t2])

    # add pd edges
    for e in zip(pd_idx.T, pd_weight.T):
        t1, t2 = protein_name_dict[e[0][0]], drug_name_dict[e[0][1]]
        G.add_edge(t1, t2, weights=e[1])
        pd_edge.append((t1, t2))
        p_node.add(t1)
        d_node.add(t2)

    # add underline pp edges
    pp_edge_idx = pp_idx.tolist()
    pp_edge_idx = set(zip(pp_edge_idx[0], pp_edge_idx[1]))
    p_node_idx = list(set(pp_idx.flatten().tolist()))
    pp_adj_idx = pp_adj.tolist()
    pp_adj_idx = set(zip(pp_adj_idx[0], pp_adj_idx[1]))

    combins = [c for c in combinations(p_node_idx, 2)]
    for i, j in combins:
        if (i, j) in pp_adj_idx or (j, i) in pp_adj_idx:
            if (i, j) not in pp_edge_idx and (j, i) not in pp_edge_idx:
                G.add_edge(protein_name_dict[i], protein_name_dict[j], weights='0')
                pp_link.append((protein_name_dict[i], protein_name_dict[j]))
    print(len(pp_link))
    # draw figure
    plt.figure(figsize=(40, 40))

    # draw nodes
    pos = nx.spring_layout(G)
    for p in d_node:  # raise drug nodes positions
        pos[p][1] += 1
    nx.draw_networkx_nodes(G, pos, nodelist=p_node, node_size=500, node_color='y')
    nx.draw_networkx_nodes(G, pos, nodelist=d_node, node_size=500, node_color='blue')

    # draw edges and edge labels
    nx.draw_networkx_edges(G, pos, edgelist=pp_edge, width=2)
    nx.draw_networkx_edges(G, pos, edgelist=pp_link, width=2, edge_color='gray', alpha=0.5)
    nx.draw_networkx_edges(G, pos, edgelist=pd_edge, width=2, edge_color='g')
    nx.draw_networkx_edge_labels(G, pos, font_size=10,
                                 edge_labels={(u, v): str(d['weights'])[:4] for
                                              u, v, d in G.edges(data=True)})

    # draw node labels
    for p in pos:  # raise text positions
        pos[p][1] += 0.04
    nx.draw_networkx_labels(G, pos, font_size=14)

    plt.savefig(out_path)