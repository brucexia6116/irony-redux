import pdb
import sqlite3
import sys
import collections
from collections import defaultdict
import re
import itertools

import nltk # for metrics

import sklearn
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.cross_validation import KFold
from sklearn.grid_search import GridSearchCV
from sklearn.svm import SVC
from sklearn.svm import LinearSVC
from sklearn.linear_model import SGDClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import precision_recall_curve

# plotting
import matplotlib.pyplot as plt
import seaborn as sns
sns.set(style="nogrid")
sns.color_palette("deep")

import scipy
import numpy as np
import statsmodels.api as sm

import search_reddit

'''
general @TODO you need to decide how to deal with comments 
labeled by different annotators! right now you are limiting
(in most places) to those labeled by the same people --
i.e., this is you use in the 'agreement' function
'''

#db_path = "/Users/bwallace/dev/computational-irony/data-11-30/ironate.db"

####
# for ACL paper: "/Users/bwallace/dev/computational-irony/data-2-7/ironate.db"

#db_path = "/Users/bwallace/dev/computational-irony/data-3-12/ironate.db"
db_path = "/home/dc65/Documents/research/irony/ironate.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
### we consider 4 active labelers
labelers_of_interest = [2,4,5,6] # TMP TMP TMP

comment_sep_str = "\n\n------------------------------------------\n"

def _make_sql_list_str(ls):
    return "(" + ",".join([str(x_i) for x_i in ls]) + ")"

labeler_id_str = _make_sql_list_str(labelers_of_interest)

def _grab_single_element(result_set, COL=0):
    return [x[COL] for x in result_set]

def _all_same(items):
    return all(x == items[0] for x in items)

def disagreed_to_disk(fout="disagreements.txt"):
    disagreement_ids, comments_to_lbls = disagreed_upon()
    conflicted_comments = grab_comments(disagreement_ids)
    out_str = []
    for i,id_ in enumerate(disagreement_ids):
        out_str.append("{0}comment id: {1}\nlabels: {2}\n{3}".format(
            comment_sep_str, id_, comments_to_lbls[id_], conflicted_comments[i]))
    
    with open(fout, 'w') as out_file:
        out_file.write("\n".join(out_str))

def disagreed_upon():
    task, tuples, comments_to_lbls = agreement()
    disagreement_ids = []
    for id_, lbls in comments_to_lbls.items():
        if not _all_same(lbls):
            disagreement_ids.append(id_)
    return disagreement_ids, comments_to_lbls

def uniform_irony_to_disk(fout="uniformly_ironic.txt"):
    irony_ids, comments_to_lbls = uniform_irony()
    uniformly_ironic_comments = grab_comments(irony_ids)
    out_str = []
    for i,id_ in enumerate(irony_ids):
        out_str.append("{0}comment id: {1}\nlabels: {2}\n{3}".format(
            comment_sep_str, id_, comments_to_lbls[id_], uniformly_ironic_comments[i]))
    
    with open(fout, 'w') as out_file:
        out_file.write("\n".join(out_str))

def subreddit_breakdown():
    pass


def majority_irony():
    task, tuples, comments_to_summary_lbls, comments_to_labeler_sets = agreement()
    maority_ironic_ids = []
    pdb.set_trace()
    for id_, lbls in comments_to_labeler_sets.items():
        #if _all_same(lbls) and lbls[0]==1:
        #    uniformly_ironic_ids.append(id_)
        if lbls.count(1) >= 2:
            majority_ironic_ids.append(id_)

    #return uniformly_ironic_ids, comments_to_lbls
    return majority_ironic_ids, comments_to_lbls

def uniform_irony():
    task, tuples, comments_to_lbls = agreement()
    uniformly_ironic_ids = []
    for id_, lbls in comments_to_lbls.items():
        if _all_same(lbls) and lbls[0]==1:
            uniformly_ironic_ids.append(id_)
    return uniformly_ironic_ids, comments_to_lbls

def any_irony():
    task, tuples, comments_to_lbls = agreement()
    at_least_one_vote = []
    for id_, lbls in comments_to_lbls.items():
        if any([y_i==1 for y_i in lbls]):
            at_least_one_vote.append(id_)
    return at_least_one_vote, comments_to_lbls

'''select comment_id from irony_label where count(*)'''
def get_labeled_thrice_comments():
    cursor.execute(
        '''select comment_id from irony_label group by comment_id having count(labeler_id) >= 3;'''
    )

    thricely_labeled_comment_ids = _grab_single_element(cursor.fetchall())

    return thricely_labeled_comment_ids

def descriptive_stats():
    thricely_labeled_comment_ids = get_labeled_thrice_comments()
    thricely_ids_str = _make_sql_list_str(thricely_labeled_comment_ids)

    subreddits =  _grab_single_element(cursor.execute(
                '''select subreddit from irony_comment where 
                        id in %s;''' % thricely_ids_str)) 

    segment_counts = _grab_single_element(cursor.execute(
            ''' select count(DISTINCT segment_id) from (select * from irony_label where
                    comment_id in %s);''' % thricely_ids_str))

                #'''select subreddit from irony_comment where 
                #        id in %s;''' % thricely_ids_str))
                #)


def comment_ids_to_human_lbls(human_id):
    cursor.execute(
        '''select distinct comment_id from irony_label 
            where forced_decision=0 and label=1 and labeler_id=%s;''' % 
            human_id)
    ironic_comments = _grab_single_element(cursor.fetchall())

    cursor.execute(
        '''select distinct comment_id from irony_label 
            where forced_decision=0 and labeler_id=%s;''' % 
            human_id)
    all_comments_labeled_by_user = _grab_single_element(cursor.fetchall())

    lbl_d = {}
    for id_ in all_comments_labeled_by_user:
        if id_ in ironic_comments:
            lbl_d[id_] = 1
        else:
            lbl_d[id_] = -1
    return lbl_d

def comment_level_computer_agreement_with_humans(comment_ids_to_preds, verbose=False):
    pairwise_kappas = []
    for human in labelers_of_interest:
        lbl_tuples = []
        ids_to_human_lbls = comment_ids_to_human_lbls(human)
        
        for comment_id, pred_lbl in comment_ids_to_preds.items():
            if comment_id in ids_to_human_lbls: 
                human_lbl = ids_to_human_lbls[comment_id]
                lbl_tuples.append(('computer', str(comment_id), str(pred_lbl)))
                lbl_tuples.append(('human', str(comment_id), str(human_lbl)))

        pw_kappa = nltk.AnnotationTask(data=lbl_tuples).kappa()
        if verbose:
            print "pairwise kappa with %s is: %s" % (human, pw_kappa)
        pairwise_kappas.append(pw_kappa)
    return sum(pairwise_kappas)/float(len(pairwise_kappas))

def computer_agreement_with_humans(segment_ids_to_preds):
    pairwise_kappas = []
    for human in labelers_of_interest:
        lbl_tuples = []
        segments_to_human_lbls = {}
        segments_and_lbls = cursor.execute(
            '''select segment_id, label from irony_label where forced_decision=0 and labeler_id=%s;''' % 
            human).fetchall()

        agreed, N = 0, 0
        for segment_id, lbl in segments_and_lbls:
            #segments_to_human_lbls[segment_id] = lbl
            if segment_id in segment_ids_to_preds: 
                #lbl_tuples.append(('human', int(segment_id), str(segment_ids_to_preds[segment_id])))#str(lbl)))
                #lbl_tuples.append(('computer', int(segment_id), str(segment_ids_to_preds[segment_id])))
                lbl_tuples.append(('computer', str(segment_id), str(segment_ids_to_preds[segment_id])))
                lbl_tuples.append(('human', str(segment_id), str(lbl) ))

                if lbl == segment_ids_to_preds[segment_id]:
                    agreed += 1
                N += 1 
        #pdb.set_trace()
        pw_kappa = nltk.AnnotationTask(data=lbl_tuples).kappa()
        print "pairwise kappa with %s is: %s" % (human, pw_kappa)
        pairwise_kappas.append(pw_kappa)
    return sum(pairwise_kappas)/float(len(pairwise_kappas))


def pairwise_kappa():
    pairwise_kappas = []
    for labeler_set in itertools.permutations(labelers_of_interest, 2):
        try:
            task, tuples, comments_to_summary_lbls, comments_to_labeler_sets = \
                agreement(these_labelers=set([str(l) for l in labeler_set]))
        except:
            pdb.set_trace()
        k = task.kappa()
        print "pairwise kappa for %s: %s" % (labeler_set, k)
        pairwise_kappas.append(k)
    return sum(pairwise_kappas)/float(len(pairwise_kappas))

# e.g., pairwise annotation task between "4" and "5" like so:
# task, tuples, comments_to_lbls, comments_to_lblers = annotation_stats.agreement(these_labelers=set(["4","5"])
def agreement(these_labelers=None, comment_level=True):
    # select all segment labels
    cursor.execute(
        '''select comment_id, segment_id, labeler_id, label from irony_label 
            where forced_decision=0 and labeler_id in %s;''' % labeler_id_str)
    all_segments = cursor.fetchall()


    comments_to_labels = defaultdict(list)
    comments_to_labeler_ids = defaultdict(list)
    for seg in all_segments:
        comment_id, segment_id, labeler, label = seg
        labeler = str(labeler)

        if comment_level:
            comments_to_labels[comment_id].append((labeler, str(segment_id), str(label)))
            comments_to_labeler_ids[comment_id].append(labeler)
        else:
            comments_to_labels[segment_id].append((labeler, str(segment_id), str(label)))
            comments_to_labeler_ids[segment_id].append(labeler)


    comments_to_labeler_sets = {}
    for comment_id, labeler_list in comments_to_labeler_ids.items():
        comments_to_labeler_sets[comment_id] = set(labeler_list)

    if these_labelers is None:
        these_labelers = set([str(l) for l in labelers_of_interest])

    # nltk wants tuples like: ('c1', '1', 'v1')
    tuples = []
    comments_to_summary_lbls = defaultdict(list)
    # now collapse 
    for i, comment_id in enumerate(comments_to_labels):
        labelers = comments_to_labeler_sets[comment_id]
        # @TODO not sure if this is how you want to deal with this, in general
        #if labelers == set([str(l) for l in labelers_of_interest]):
        #pdb.set_trace()
        if these_labelers.issubset(labelers):
            comment_labels = comments_to_labels[comment_id]
            was_labeled_by = lambda a_label, a_labeler : a_label[0] == a_labeler
            for labeler in these_labelers:
                labeler_labels = [
                    int(lbl_tuple[-1]) for lbl_tuple in comment_labels if
                         was_labeled_by(lbl_tuple, labeler)]
                # call it a 1 if any were 1 (for this labeler!) 
                labeler_aggregate_label = max(labeler_labels)
                comments_to_summary_lbls[str(comment_id)].append(labeler_aggregate_label)
                cur_tuple = (str(labeler), str(comment_id), str(labeler_aggregate_label))
                tuples.append(cur_tuple)

    #pdb.set_trace()
    task = nltk.AnnotationTask(data=tuples)

    #print "kappa is: {0}".format(task.kappa())

    #pdb.set_trace()
    return task, tuples, comments_to_summary_lbls, comments_to_labeler_sets


def plot_confidence_changes():
    from matplotlib import rc
    rc('font',**{'family':'sans-serif','sans-serif':['Helvetica']})
    rc('text', usetex=True)

    confidence_dict = confidence_change_forced()
    ### average over labelers
    labeler_changed_mind_d = defaultdict(list)
    labeler_conf_delta = defaultdict(list)
    
    labeler_delta_plot_d = defaultdict(dict)
    for labeler in labelers_of_interest:
        labeler_delta_plot_d[labeler] = {
                            "00":{"count":0, "confidences":[]},
                            "11":{"count":0, "confidences":[]},
                            "01":{"count":0, "confidences":[]},
                            "10":{"count":0, "confidences":[]}}

    bool_to_dummy = lambda x: 1 if x>0 else 0
    decisions_to_str = lambda d0, d1: "%s%s" % (
                            bool_to_dummy(d0), bool_to_dummy(d1))


    before_after_counts = {"00":0, "11":0, "01":0, "10":0}
    better_titles = {"00":r"unironic $\rightarrow$ unironic", 
                     "11":"blah", "01":"blah", "10":"10"}
                        
                        #"final":(final_max_lbl, final_conf),
                        #"forced": (forced_max_lbl, forced_conf) 

    for comment in confidence_dict:
        for labeler, lbl_dict in confidence_dict[comment].items():
            d0 = lbl_dict['forced'][0]
            d1 = lbl_dict['final'][0]
            changed_mind = d0!=d1
            labeler_changed_mind_d[labeler].append(bool_to_dummy(changed_mind))

            c0 = lbl_dict['forced'][1]
            c1 = lbl_dict['final'][1] 
            conf_delta = c1 - c0
            labeler_conf_delta[labeler].append(conf_delta)
            
            box_str = decisions_to_str(d0, d1)
            #pdb.set_trace()
            labeler_delta_plot_d[labeler][box_str]["count"] += 1
            labeler_delta_plot_d[labeler][box_str]["confidences"].append((c0, c1))

    for labeler in labelers_of_interest:
        plt.clf()
        decision_strs = before_after_counts.keys()
        labeler_data = labeler_delta_plot_d[labeler]
        
        z_conf = 3.0
        #for decision_str in decision_strs:
        #    z_conf = max()
        from matplotlib import gridspec
        # gs =  gridspec.GridSpec(4, 1, height_ratios=[1, 1 ,1.5, 1])
        frame, axes = plt.subplots(4, 2, sharex=True, sharey=True)
        frame.set_figwidth(5)
        #frame.set_figwidth(4)

        frame.subplots_adjust(hspace=0, wspace=0)
        plt.setp([a.get_xticklabels() for a in axes[0, :]], visible=False)

        # bottom two
        for j in xrange(2):
            axes[-1][j].xaxis.set_ticks([])

        axes[-1][0].set_xlabel("forced decision", size=22)
        axes[-1][1].set_xlabel("final decision", size=22)

        #axes[-1][1].xaxis.set_visible(False)
        cool, warm = sns.color_palette("coolwarm", 2) 
        Blues = plt.get_cmap('Blues')
        Reds = plt.get_cmap('Reds')
        Grays = plt.get_cmap('gray')
        for i in xrange(4):
            decision_data = labeler_data[decision_strs[i]]
            count = decision_data['count']
            axes[i][0].yaxis.set_ticks([])#set_visible(False)
            #axes[i][0].set_ylabel("%s \n (%s)" % 
            #            (better_titles[decision_strs[i]], count), 
            #            rotation="horizontal")
            axes[i][0].set_ylabel("%s" % count, rotation="horizontal", size=18)
            axes[i][0].yaxis.set_label_position("right")

            confidences = []
            # before
            conf0 = [c[0] for c in decision_data["confidences"]]
            avg_conf0 = sum(conf0)/float(len(conf0))

            if i % 2 == 0:
                color0 = Blues(avg_conf0)
                #color0 = Blacks()
            else:
                color0 = Reds(avg_conf0)
            #color0 = Grays(avg_conf0)
            axes[i][0].set_axis_bgcolor(color0)

            # after
            conf1 = [c[1] for c in decision_data["confidences"]]
            avg_conf1 = sum(conf1)/float(len(conf1))

            if i % 2 == 0:
                color1 = Blues(avg_conf1)
            else:
                color1 = Reds(avg_conf1)
            #color1 = Grays(avg_conf1)
            axes[i][1].set_axis_bgcolor(color1)
            #
        #frame.tight_layout()
        plt.savefig("%s.pdf" % labeler)
        print decision_strs

def confidence_change_forced():

    triply_labeled_comment_ids = get_labeled_thrice_comments()
    triply_labeled_comments_str = _make_sql_list_str(triply_labeled_comment_ids)

    final_decisions =  list(cursor.execute(
        '''select labeler_id, comment_id, label, confidence from irony_label 
            where forced_decision=0 and comment_id in %s and labeler_id in %s;''' % 
            (triply_labeled_comments_str, labeler_id_str)))



    # collapse final decision into dictionary mapping comment ids to 
    # dictionaries that in turn map to decisions
    final_labels_dict = defaultdict(lambda: defaultdict(list))
    comments = []
    for labeler_id, comment_id, label, confidence in final_decisions:
        final_labels_dict[comment_id][labeler_id].append((label, confidence))
        comments.append(comment_id)

    comments = list(set(comments))

    ###
    # forced labels!
    forced_decisions = list(cursor.execute(
                '''select labeler_id, comment_id, label, confidence from irony_label where 
                    forced_decision=1 and comment_id in %s and labeler_id in %s;''' % 
                    (triply_labeled_comments_str, labeler_id_str)))

    forced_labels_dict = defaultdict(lambda: defaultdict(list))
    for labeler_id, comment_id, label, confidence in forced_decisions:
        forced_labels_dict[comment_id][labeler_id].append((label, confidence))
        


    # now just call the comment a 1 if any segment in it
    # is a 1
    collapsed_final_labels_dict = defaultdict(lambda: defaultdict(list))
    collapsed_forced_labels_dict = defaultdict(lambda: defaultdict(list))
    final_and_forced_dict = defaultdict(lambda: defaultdict(dict))
    filter_these = []
    for comment in comments:
        if comment in forced_labels_dict.keys():
            for labeler in labelers_of_interest:
                if len(forced_labels_dict[comment][labeler]) > 0 and len(
                        final_labels_dict[comment][labeler]):
                    final_max_lbl = max([x[0] for x in final_labels_dict[comment][labeler]])
                    final_conf = final_labels_dict[comment][labeler][0][1]
                    forced_max_lbl = max([x[0] for x in forced_labels_dict[comment][labeler]])
                    forced_conf = forced_labels_dict[comment][labeler][0][1]
                    final_and_forced_dict[comment][labeler] = {
                        "final":(final_max_lbl, final_conf),
                        "forced": (forced_max_lbl, forced_conf) 
                    }

                '''
                if len(final_labels_dict[comment][labeler]) > 0:
                    final_max_lbl = max([x[0] for x in final_labels_dict[comment][labeler]])
                    # these will be the same for all segments!
                    final_conf = final_labels_dict[comment][labeler][0][1]
                    collapsed_final_labels_dict[comment][labeler] = (max_lbl, conf)

                if len(forced_labels_dict[comment][labeler]) > 0:
                    forced_max_lbl = max([x[0] for x in forced_labels_dict[comment][labeler]])
                    forced_conf = forced_labels_dict[comment][labeler][0][1]
                    collapsed_forced_labels_dict[comment][labeler] = (max_lbl, conf)
                '''

            #else:
            #    pdb.set_trace()
            #    filter_these.append(comment)


    
    #return collapsed_labels_dict, ironic_comments
    # now, look at
    #return collapsed_forced_labels_dict, collapsed_final_labels_dict
    return final_and_forced_dict

def n_users_requested_context_for_comment(comment_id):
    ''' how many annotators requested context for this comment? '''
    forced_decisions = _grab_single_element(cursor.execute(
                '''select distinct labeler_id from irony_label where forced_decision=1 and comment_id =%s and labeler_id in %s;''' % 
                   (comment_id, labeler_id_str)))
    return forced_decisions


def n_users_labeled_as_irony(comment_id):
    ''' how many annotators labeled this comment as containing some irony? '''
    ironic_lblers = _grab_single_element(cursor.execute(
        '''select distinct labeler_id from irony_label 
            where forced_decision=0 and comment_id = %s and label=1 and labeler_id in %s;''' % 
            (comment_id, labeler_id_str)))
    return ironic_lblers

def get_forced_comments():
    # pre-context / forced decisions
    forced_decisions = _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where forced_decision=1 and labeler_id in %s;''' % 
                    labeler_id_str)) 

    forced_decisions_str = _make_sql_list_str(forced_decisions)
    comment_urls = cursor.execute(
                '''select id, thread_url, permalink, subreddit from irony_comment where id in %s;''' % 
                forced_decisions_str).fetchall()


    #pdb.set_trace()
    #p_forced = float(len(forced_decisions)) / float(len(all_comment_ids))

    # now look at the proportion forced for the ironic comments
    ironic_comments = get_ironic_comment_ids()

    # which were labeled ironic?
    irony_labels = []
    for comment_id in forced_decisions:
        if comment_id in ironic_comments:
            irony_labels.append(1)
        else:
            irony_labels.append(0)

    ironic_ids_str = _make_sql_list_str(ironic_comments)
    forced_ironic_ids =  _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where 
                        forced_decision=1 and comment_id in %s and labeler_id in %s;''' % 
                                (ironic_ids_str, labeler_id_str))) 
    #return dict(zip(forced_ironic_ids, grab_comments(forced_ironic_ids)))
    return zip(grab_comments(forced_decisions), irony_labels, comment_urls)

def get_ironic_comment_ids():
    cursor.execute(
        '''select distinct comment_id from irony_label 
            where forced_decision=0 and label=1 and labeler_id in %s;''' % 
            labeler_id_str)

    ironic_comments = _grab_single_element(cursor.fetchall())
    return ironic_comments

def get_ironic_comment_ids_at_least(at_least=2):
    cursor.execute(
        '''select distinct comment_id from irony_label 
            where forced_decision=0 and label=1 and labeler_id in %s;''' % 
            labeler_id_str)
    
    def count_positive_labels(comment_id):
        unique_labelers = cursor.execute(
            '''select distinct labeler_id from irony_label where 
                    forced_decision=0 and label=1 and comment_id=%s;''' % comment_id).fetchall()
        n_labelers = len(unique_labelers)
        return n_labelers

    # this list contains all comments labeled by at least one
    # person as containing irony
    ironic_comments = _grab_single_element(cursor.fetchall())
    # now filter it - i'm sure this is a stupid way of doing this.
    comments_labeled_at_least = []
    for comment_id in ironic_comments:
        if count_positive_labels(comment_id) >= at_least:
            comments_labeled_at_least.append(comment_id)

    return comments_labeled_at_least 


def naive_irony_prop():
    # comments that at least one person has labeled one sentence within as being 
    # ironic
    #cursor.execute("select distinct comment_id from irony_label where forced_decision=0 and label=1;")
    # restricting to a subset of lablers for now!
    ironic_comments = get_ironic_comment_ids()

    # all comments
    cursor.execute(
        '''select distinct comment_id from irony_label where forced_decision=0 and
            labeler_id in %s;''' % labeler_id_str)
    all_comments = _grab_single_element(cursor.fetchall())

    n_ironic = float(len(ironic_comments))
    N = float(len(all_comments))
    return n_ironic, N, ironic_comments, all_comments

def get_all_comment_ids():
    return _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where labeler_id in %s;''' % 
                    labeler_id_str)) 

def context_stats():
    all_comment_ids = get_all_comment_ids()

    # pre-context / forced decisions
    forced_decisions = _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where forced_decision=1 and labeler_id in %s;''' % 
                    labeler_id_str)) 

    for labeler in labelers_of_interest:
        labeler_forced_decisions = _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where forced_decision=1 and labeler_id = %s;''' % 
                    labeler))

        all_labeler_decisions = _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where forced_decision=0 and labeler_id = %s;''' % 
                    labeler))

        p_labeler_forced = float(len(labeler_forced_decisions))/float(len(all_labeler_decisions))
        print "labeler %s: %s" % (labeler, p_labeler_forced)

    pdb.set_trace()
    p_forced = float(len(forced_decisions)) / float(len(all_comment_ids))

    # now look at the proportion forced for the ironic comments
    ironic_comments = get_ironic_comment_ids()
    ironic_ids_str = _make_sql_list_str(ironic_comments)
    forced_ironic_ids =  _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where 
                        forced_decision=1 and comment_id in %s and labeler_id in %s;''' % 
                                (ironic_ids_str, labeler_id_str))) 

    '''
    regression bit.
    '''
    X,y = [],[]
    ### only include those that have been labeled by everyone for now
    #task, tuples, comments_to_summary_lbls, comments_to_labelers = agreement()
    #all_comment_ids = [int(id_) for id_ in comments_to_summary_lbls.keys()]

    for c_id in all_comment_ids:
        if c_id in forced_decisions:
            y.append(1.0)
        else:
            y.append(0.0)

        if c_id in ironic_comments:
            X.append([1.0])
        else:
            X.append([0.0])

    X = sm.add_constant(X, prepend=True)
    #pdb.set_trace()
    logit_mod = sm.Logit(y, X)
    logit_res = logit_mod.fit()
    
    print logit_res.summary()
    return logit_res

def get_ironic_comments(urls_too=False):
    ironic_ids = get_ironic_comment_ids()
    comments = grab_comments(ironic_ids)
    if not urls_too:
        return comments

    urls = []
    for comment_id in ironic_ids:
        urls.append(_grab_single_element(
            cursor.execute("select permalink from irony_comment where id='%s'" % comment_id)))
    #pdb.set_trace()
    return (comments, urls)
        

def get_labeled_comment_breakdown():
    pass

def _get_entries(a_list, indices):
    return [a_list[i] for i in indices]

def get_NNPs_from_comment(comment):
    NNPs = []
    for sentence in nltk.sent_tokenize(comment):
        tokenized_sent = nltk.word_tokenize(sentence)
        pos_tags = nltk.pos_tag(tokenized_sent)
        NNPs.extend([t[0] for t in pos_tags if t[1]=="NNP"])
    return NNPs

def get_all_NNPs():
    comments = get_labeled_thrice_comments()
    comments_str = _make_sql_list_str(comments)
    comments_and_redditors = list(cursor.execute(
                '''select id, redditor, subreddit from irony_comment where id in %s;''' % 
                comments_str))
    
    comment_ids = [comment[0] for comment in comments_and_redditors]
    comment_texts = grab_comments(comment_ids)

    # yes, inefficient
    users = [comment[1] for comment in comments_and_redditors]
    subreddits = [comment[-1] for comment in comments_and_redditors]

    #comment_NNPs = []
    related_subreddit_comments, related_user_comments = [], []
    for i, comment in enumerate(comment_texts[:5]):
        print "on comment %s" % (i+1)
        NNPs = get_NNPs_from_comment(comment)
        subreddit = subreddits[i]
        user = users[i]
        #comment_NNPs.append(NNPs)
        related_subreddit_comments_i, related_user_comments_i = [], []
        for NNP in NNPs:
            related_subreddit_comments_i.extend(
                [c.body for c in search_reddit.search_subreddit_comments(NNP, subreddit)])
            related_user_comments_i.extend(
                [c.body for c in search_reddit.search_comments_by_user(NNP, user)])
        
        related_subreddit_comments.append(related_subreddit_comments_i)
        related_user_comments.append(related_user_comments_i)

    #return comments, comment_NNPs, labels
    pdb.set_trace()


def get_comments_and_labels():
    all_comment_ids = get_labeled_thrice_comments()


    # now look at the proportion forced for the ironic comments
    ironic_comment_ids = get_ironic_comment_ids()
    #ironic_ids_str = _make_sql_list_str(ironic_comments)


    forced_decision_ids = _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where forced_decision=1 and labeler_id in %s;''' % 
                    labeler_id_str)) 

    comment_texts, y = [], []
    for id_ in all_comment_ids:
        comment_texts.append(grab_comments([id_])[0])
        if id_ in ironic_comment_ids:
            y.append(1)
        else:
            y.append(-1)

    return comment_texts, y


def _get_subreddits(comment_ids):
    srs = []
    for c_id in comment_ids:
        sr = _grab_single_element(
            cursor.execute('''select subreddit from irony_comment where id=%s''' % c_id))
        srs.append(sr[0])
    return srs

def get_all_sentences_from_subreddit(subreddit):
    cursor.execute(
        '''select distinct segment_id from irony_label where 
                comment_id in (select id from irony_comment where subreddit='%s');''' % 
                    subreddit
    )
    subreddit_sentences = _grab_single_element(cursor.fetchall())
    return list(set(subreddit_sentences))


def get_sentence_ids_for_comment(comment_id):
    # syntactic sugar.
    sentence_ids, subreddits = get_sentence_ids_for_comments([comment_id])
    # all the subreddits are the same, of course, so just return the first.
    return (sentence_ids, subreddits[0])

def get_sentence_ids_for_comments(comment_ids):
    comments_ids_str = _make_sql_list_str(comment_ids)

    segment_ids_and_srs = cursor.execute(
            '''select irony_commentsegment.id, subreddit from irony_commentsegment, irony_comment 
                where irony_comment.id=irony_commentsegment.comment_id and irony_comment.id in %s 
                order by irony_commentsegment.id;''' % comments_ids_str).fetchall()

    sentence_ids, subreddits = [],[]
    for segment in segment_ids_and_srs:
        sentence_ids.append(segment[0])
        subreddits.append(segment[1])

    return (sentence_ids, subreddits)

def get_texts_and_labels_for_sentences(sentence_ids, repeat=False, collapse=max):

    # this is naive...
    sentence_texts, sentence_lbls = [], []
    new_sentence_ids = [] # only relevant if we're 'repeating' (replicating sentences)
    for id_ in sentence_ids:
        sentence_text = cursor.execute(
                    '''select text from irony_commentsegment where id=%s;''' % id_).fetchall()[0][0]

        sentence_text = add_punctuation_features(sentence_text)
        if not repeat:
            sentence_texts.append(sentence_text)
            new_sentence_ids.append(id_)
        else:
            sentence_texts.extend([sentence_text, sentence_text, sentence_text])
            new_sentence_ids.extend([id_, id_, id_])

      
        lbls = [lbls[0] for lbls in cursor.execute(
                '''select label from irony_label where segment_id=%s
                    and forced_decision=0 order by segment_id;''' % id_).fetchall()]
        if not repeat:
            sentence_lbls.append(collapse(lbls))
        else:
            sentence_lbls.extend(lbls)
    
    return (new_sentence_ids, sentence_texts, sentence_lbls)


def get_all_comments_from_subreddit(subreddit):
    #all_comment_ids = get_labeled_thrice_comments()
    #subreddits = _get_subreddits(all_comment_ids)
    #filtered = 
    cursor.execute(
        '''select distinct comment_id from irony_label where 
                comment_id in (select id from irony_comment where subreddit='%s');''' % 
                    subreddit
    )
    subreddit_comments = _grab_single_element(cursor.fetchall())
    return list(set(subreddit_comments))


def sentence_classification_i(add_interactions=True, model="SVC", verbose=False):
    ''' interaction features '''
    from sklearn.feature_extraction.text2 import InteractionTermCountVectorizer

    labeled_comment_ids = get_labeled_thrice_comments()
    conservative_comment_ids = list(set([c_id for c_id in 
            get_all_comments_from_subreddit("Conservative") if c_id in labeled_comment_ids]))

    n_conservative_comments = len(conservative_comment_ids)
    liberal_comment_ids = list(set([c_id for c_id in 
                get_all_comments_from_subreddit("progressive") if c_id in labeled_comment_ids]))

    all_comment_ids = conservative_comment_ids + liberal_comment_ids
    sentence_ids, subreddits = get_sentence_ids_for_comments(all_comment_ids)
    sent_ids_to_subreddits = dict(zip(sentence_ids, subreddits))

    # ok now get text and labels
    collapse_f = lambda lbl_set: 1 if lbl_set.count(1) >= 2 else -1
    sentence_ids, sentence_texts, sentence_lbls = get_texts_and_labels_for_sentences(
        sentence_ids, repeat=False, collapse=collapse_f)

    if add_interactions:
        vectorizer = InteractionTermCountVectorizer(ngram_range=(1,2), 
                                        stop_words="english", binary=True)
        # add interaction terms for liberals
        interaction_indices = [s_i for s_i in xrange(len(sentence_ids)) 
                                if subreddits[s_i] == "progressive"]
        X = vectorizer.fit_transform(sentence_texts, interaction_prefix="progressive",
                                    interaction_doc_indices=interaction_indices)

    else:
        vectorizer = CountVectorizer(ngram_range=(1,2), 
                                        stop_words="english", binary=True)
        X = vectorizer.fit_transform(sentence_texts)
    #X = vectorizer.fit_transform(sentence_texts)
    #pdb.set_trace()

    # @TODO!
    #y = [max(lbls) for lbls in sentence_lbls]
    y = sentence_lbls      

    kf = KFold(len(y), n_folds=5, shuffle=True, random_state=9)
    recalls, precisions, Fs = [], [], []
    kappas = []
    #results = []
    for train, test in kf:
        #train_ids = _get_entries(all_comment_ids, train)
        test_ids = _get_entries(sentence_ids, test)
        y_train = _get_entries(y, train)
        y_test = _get_entries(y, test)

        X_train, X_test = X[train], X[test]
        
        clf = None
        if model=="SGD":
            print "SGD!!!"
            svm = SGDClassifier(loss="hinge", penalty="l2", class_weight="auto")
            parameters = {'alpha':[.0001, .001, .01, .1, 1, 10, 100]}
            clf = GridSearchCV(svm, parameters, scoring='f1')
        elif model == "SVC":
            print "SVC!!!!"
            svc = LinearSVC(loss="l2", penalty="l2", dual=False, class_weight="auto")
            parameters = {'C':[ .001, .01,  .1, 1, 10, 100]}
            clf = GridSearchCV(svc, parameters, scoring='f1')

        clf.fit(X_train, y_train)
        
        preds = clf.predict(X_test)
        if verbose:
            print show_most_informative_features(vectorizer, clf.best_estimator_)

        print sklearn.metrics.classification_report(y_test, preds)
        
        #pdb.set_trace()
        prec, recall, f, support = sklearn.metrics.precision_recall_fscore_support(
                                    y_test, preds)
        recalls.append(recall)
        precisions.append(prec)
        Fs.append(f)

        segments_to_preds = dict(zip(test_ids, preds))
        kappa = computer_agreement_with_humans(segments_to_preds)
        print "avg kappa: %s" % kappa
        kappas.append(kappa)

    avg = lambda l : sum(l)/float(len(l))
    print "average F: %s \naverage recall: %s \naverage precision: %s " % (
                avg(Fs), avg(recalls), avg(precisions))
    print "average (average) kappa: %s\n" % avg(kappas)

    return Fs, recalls, precisions, kappas







def sentence_classification(use_pretense=False, model="SVC", interaction_features=False, verbose=False):
    print "-- sentence classification! ---"
    # @TODO refactor -- this is redundant with code above!!!
    # only keep the sentences for which we have 'final' comment 
    # labels.
    labeled_comment_ids = get_labeled_thrice_comments()
    conservative_comment_ids = list(set([c_id for c_id in 
            get_all_comments_from_subreddit("Conservative") if c_id in labeled_comment_ids]))

    n_conservative_comments = len(conservative_comment_ids)
    liberal_comment_ids = list(set([c_id for c_id in 
                get_all_comments_from_subreddit("progressive") if c_id in labeled_comment_ids]))

    all_comment_ids = conservative_comment_ids + liberal_comment_ids

    sent_ids_to_subreddits = {}
    comments_d = {} # point from comment_id to sentences, etc.
    for comment_id in all_comment_ids:
        comment_sentence_ids, comment_subreddit = get_sentence_ids_for_comment(comment_id)
        comments_d[comment_id] = {"sentence_ids":comment_sentence_ids, 
                                    "subreddit":comment_subreddit}
        for sent_id in comment_sentence_ids:
            sent_ids_to_subreddits[sent_id] = comment_subreddit

        #sentence_ids.append(comment_sentence_ids)
        #subreddits.append()

    #all_sentence_ids = [comment["sentence_ids"] for comment in comments_d.values()]
    all_sentence_ids = []
    for comment in comments_d.values():
        all_sentence_ids.extend(comment["sentence_ids"])

    # ok now get text and labels
    collapse_f = lambda lbl_set: 1 if lbl_set.count(1) >= 2 else -1

    # perhaps return comment ids here
    all_sentence_ids, sentence_texts, sentence_lbls = get_texts_and_labels_for_sentences(
        all_sentence_ids, repeat=False, collapse=collapse_f)
    sentence_ids_to_labels = dict(zip(all_sentence_ids, sentence_lbls))
    sentence_ids_to_rows = dict(zip(all_sentence_ids, range(len(all_sentence_ids))))

    vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(
                                        max_features=10000, ngram_range=(1,2), 
                                        stop_words="english")
    X = vectorizer.fit_transform(sentence_texts)

    # @TODO!
    #y = [max(lbls) for lbls in sentence_lbls]
    #y = sentence_lbls

    predicted_probabilities_of_being_liberal = []
    if use_pretense:
        clf, vectorizer = sentence_liberal_conservative_model()#pretense(just_the_model=True)
        Xliberal = vectorizer.transform(sentence_texts)
        #X = vectorizer.fit_transform(comment_texts)
        for x_i in Xliberal:
            p_i = clf.predict_proba(x_i)[0][1]
            predicted_probabilities_of_being_liberal.append(p_i)

        ####
        x0 = scipy.sparse.csr.csr_matrix(np.zeros((X.shape[0], 3)))
        X = scipy.sparse.hstack((X, x0)).tocsr()
    
        conservative_j = X.shape[1] - 1
        liberal_j = X.shape[1] - 2
        for i in xrange(X.shape[0]):
            sentence_id = all_sentence_ids[i]
            #if i < n_conservative_comments:
            if sent_ids_to_subreddits[sentence_id] == "Conservative":
                X[i,conservative_j] = predicted_probabilities_of_being_liberal[i]
                #pass
            else:
                X[i, liberal_j-1] = 1.0 # 'liberal intercept'
                X[i,liberal_j] = predicted_probabilities_of_being_liberal[i]


    #kf = KFold(len(y), n_folds=10, shuffle=True, random_state=1069)
    # move the folds to the *comment* level
    kf = KFold(len(all_comment_ids), n_folds=5, shuffle=True, random_state=1069)

    recalls, precisions, Fs = [], [], []
    kappas = []
    #results = []
    ### TODO finish this! we'll move to shuffling comments and training
    ### on their sentences
    for train, test in kf:

        train_comment_ids = _get_entries(all_comment_ids, train)
        test_comment_ids = _get_entries(all_comment_ids, test)
        train_rows, y_train = [], []
        test_rows, y_test = [], []

        for comment in train_comment_ids:
            sentence_ids = comments_d[comment]["sentence_ids"]
            train_rows.extend([sentence_ids_to_rows[sent_id] for sent_id in sentence_ids])
            y_train.extend([sentence_ids_to_labels[sent_id] for sent_id in sentence_ids])

        for comment in test_comment_ids:
            sentence_ids = comments_d[comment]["sentence_ids"]
            test_rows.extend([sentence_ids_to_rows[sent_id] for sent_id in sentence_ids])
            y_test.extend([sentence_ids_to_labels[sent_id] for sent_id in sentence_ids])

        #y_train = _get_entries(y, train)
        #y_test = _get_entries(y, test)

        X_train, X_test = X[train_rows], X[test_rows]
        
        clf = None
        if model=="SGD":
            print "SGD!!!"
            svm = SGDClassifier(loss="hinge", penalty="l2", class_weight="auto")
            parameters = {'alpha':[.0001, .001, .01, .1, 1, 10, 100]}
            clf = GridSearchCV(svm, parameters, scoring='f1')
        elif model == "SVC":
            print "SVC!!!!"
            svc = LinearSVC(loss="l2", penalty="l2", dual=False, class_weight="auto")
            parameters = {'C':[ .001, .01,  .1, 1, 10, 100]}
            clf = GridSearchCV(svc, parameters, scoring='f1')
        elif model=="baseline":
            import random
            # guess at chance
            p_train = len([y_i for y_i in y_train if y_i > 0])/float(len(y_train))
            def baseline_clf(): # no input!
                if random.random() < p_train:
                    return 1
                return -1
            clf = baseline_clf

        if not model=="baseline":
            clf.fit(X_train, y_train)
            preds = clf.predict(X_test)
        else:
            preds = [clf() for i in xrange(len(y_test))]

        if verbose:
            print show_most_informative_features(vectorizer, clf.best_estimator_)

        print sklearn.metrics.classification_report(y_test, preds)
        
        #pdb.set_trace()
        prec, recall, f, support = sklearn.metrics.precision_recall_fscore_support(
                                    y_test, preds)
        recalls.append(recall)
        precisions.append(prec)
        Fs.append(f)

        #segments_to_preds = dict(zip(test_ids, preds))
        #kappa = computer_agreement_with_humans(segments_to_preds)
        #print "avg kappa: %s" % kappa
        #kappas.append(kappa)

    avg = lambda l : sum(l)/float(len(l))
    print "average F: %s \naverage recall: %s \naverage precision: %s " % (
                avg(Fs), avg(recalls), avg(precisions))
    #print "average (average) kappa: %s\n" % avg(kappas)

    return Fs, recalls, precisions#, kappas

def sentence_liberal_conservative_model():
    conservative_comment_ids = get_all_comments_from_subreddit("Conservative")
    liberal_comment_ids = get_all_comments_from_subreddit("progressive")
    conservative_ids, conservative_texts, conservative_y = get_texts_and_labels_for_sentences(conservative_comment_ids)
    liberal_ids, liberal_texts, liberal_y = get_texts_and_labels_for_sentences(liberal_comment_ids)

    y = [-1 for i in xrange(len(conservative_ids))] + [1 for i in xrange(len(liberal_ids))] 
    sentence_texts = conservative_texts + liberal_texts
    vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(
                    max_features=20000, ngram_range=(1,2), stop_words="english")
    X = vectorizer.fit_transform(sentence_texts)

    clf = sklearn.linear_model.LogisticRegression()
    clf.fit(X, y)
    #pdb.set_trace()
    return clf, vectorizer

### @experimental!
def pretense(just_the_model=False):

    #all_comment_ids = get_labeled_thrice_comments()
    #conservative_comments, liberal_comments = [], []
    #pass
    conservative_comment_ids = get_all_comments_from_subreddit("Conservative")
    conservative_comments = grab_comments(conservative_comment_ids)
    liberal_comment_ids = get_all_comments_from_subreddit("progressive")
    liberal_comments = grab_comments(liberal_comment_ids)
    comment_texts = conservative_comments + liberal_comments
    vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(
                    max_features=20000, ngram_range=(1,2), stop_words="english")
    X = vectorizer.fit_transform(comment_texts)
    y = [0 for y_i in xrange(len(conservative_comments))] + [1 for y_i in xrange(len(liberal_comments))]
    

    #clf = MultinomialNB(alpha=5)
    clf = sklearn.linear_model.LogisticRegression()
    clf.fit(X, y)
    if just_the_model:
        ''' just return the trained progressive/conservative classifier '''
        return clf, vectorizer


    ironic_comment_ids =  get_ironic_comment_ids_at_least(1)#get_ironic_comment_ids()

    '''
    conservative comments...
    '''
    n_conservative = len(conservative_comment_ids)
    conservative_ironic = [i for i in xrange(n_conservative) if 
                            conservative_comment_ids[i] in ironic_comment_ids]
    X_conservative, y_conservative = [], []
    unironic_conservative_ps, ironic_conservative_ps = [], []
    for i in xrange(n_conservative):
        x_i = X[i]
        p_i = clf.predict_proba(X[i])[0][1]
        X_conservative.append([p_i])

        if i in conservative_ironic:
            ironic_conservative_ps.append(p_i)
            y_conservative.append(1)
        else:
            unironic_conservative_ps.append(p_i)
            y_conservative.append(0)

    X_conservative = sm.add_constant(X_conservative, prepend=True)
    logit_mod = sm.Logit(y_conservative, X_conservative)
    logit_res = logit_mod.fit()
    print " --- conservative ---"
    print logit_res.summary()
    #pdb.set_trace()

    n_liberal = len(liberal_comment_ids)
    liberal_ironic = [i for i in xrange(n_liberal) if 
                            liberal_comment_ids[i] in ironic_comment_ids]

    unironic_liberal_ps, ironic_liberal_ps = [], []
    X_liberal, y_liberal = [], []
    for i in xrange(n_liberal):
        # note the offset
        x_i = X[n_conservative + i]
        p_i = clf.predict_proba(x_i)[0][1]
        X_liberal.append([p_i])
        if i in liberal_ironic:
            ironic_liberal_ps.append(p_i)
            y_liberal.append(1)
        else:
            unironic_liberal_ps.append(p_i)
            y_liberal.append(0)


    X_liberal = sm.add_constant(X_liberal, prepend=True)
    #pdb.set_trace()
    logit_mod = sm.Logit(y_liberal, X_liberal)
    logit_res = logit_mod.fit()
    print "\n --- liberal ---"
    print logit_res.summary()


    ironic_liberal_avg = sum(ironic_liberal_ps)/float(len(ironic_liberal_ps))
    unironic_liberal_avg = sum(unironic_liberal_ps)/float(len(unironic_liberal_ps))
    #pdb.set_trace()


'''
human baseline
'''
def human_baseline():
    for human in labelers_of_interest:
        pass

'''
pretense_baseline and pretense both use only comments from progressive
and conservative subreddits. If pretense is true, we add the 'pretense'
feature for prediction
'''
def pretense_experiment(use_pretense=False, at_least=1, model="SGD", 
                        verbose=False, interaction_features=False):
    print "building progressive/conservative model!"
    # @TODO refactor -- this is redundant with code above!!!
    labeled_comment_ids = get_labeled_thrice_comments()
    conservative_comment_ids = list(set([c_id for c_id in 
            get_all_comments_from_subreddit("Conservative") if c_id in labeled_comment_ids]))

    n_conservative_comments = len(conservative_comment_ids)
    liberal_comment_ids = list(set([c_id for c_id in 
                get_all_comments_from_subreddit("progressive") if c_id in labeled_comment_ids]))

    all_comment_ids = conservative_comment_ids + liberal_comment_ids
    #pdb.set_trace()
    #all_comment_ids = list(set(all_comment_ids))
    ironic_comment_ids = get_ironic_comment_ids_at_least(at_least)
    #ironic_comment_ids = majority_irony()[0]
    
    #all_comment_ids = [c_id for c_id in all_comment_ids if c_id in labeled_comment_ids]
    
    predicted_probabilities_of_being_liberal = []
    if use_pretense:
        clf, vectorizer = pretense(just_the_model=True)
        X = vectorizer.transform(grab_comments(all_comment_ids))
        #X = vectorizer.fit_transform(comment_texts)
        for x_i in X:
            #p_i = clf.predict_proba(x_i)[0][1]
            p_i = clf.predict(x_i)[0]
            #pdb.set_trace()
            predicted_probabilities_of_being_liberal.append(p_i)
    #pdb.set_trace()
        
    comment_texts, y = [], []
    for id_ in all_comment_ids:
        comment_texts.append(grab_comments([id_])[0])
        if id_ in ironic_comment_ids:
            y.append(1)
        else:
            y.append(-1)


    vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(
                                        max_features=10000, ngram_range=(1,2), 
                                        stop_words="english")
    X = vectorizer.fit_transform(comment_texts)
    
    x0 = scipy.sparse.csr.csr_matrix(np.zeros((X.shape[0], 4)))
    X = scipy.sparse.hstack((X, x0)).tocsr()
    
    ###
    # now add pretense features!
    if use_pretense:
        conservative_j = X.shape[1] - 1
        liberal_j = X.shape[1] - 3

        # for each instance, add an interaction 
        # (political or liberal subreddit x predicted political orientation)
        #for i in xrange(X.shape[0]):
        #    X[i,liberal_j] = predicted_probabilities_of_being_liberal[i]
        
        for i in xrange(X.shape[0]):
            if not interaction_features:
                # just one feature (not crossed with subreddit)
                X[i,liberal_j] = predicted_probabilities_of_being_liberal[i]#1.0

            else:
                # interaction features
                if i < n_conservative_comments:
                    #pdb.set_trace()
                    X[i,conservative_j-1] = 1.0
                    X[i,conservative_j] = predicted_probabilities_of_being_liberal[i]

                else:
                    X[i, liberal_j-1] = 1.0 # 'liberal intercept'
                    X[i,liberal_j] = predicted_probabilities_of_being_liberal[i]
                    #pass
                    #X[i,liberal_i] = 1
            
            ### SANITY CHECK BY CHEATING
            #X[i,conservative_j] = y[i]
    #pdb.set_trace()
    kf = KFold(len(y), n_folds=5, shuffle=True, random_state=5)
    recalls, precisions, Fs, AUCs = [], [], [], []
    avg_pw_kappas = []
    test_comments = []

    for train, test in kf:
        train_ids = _get_entries(all_comment_ids, train)
        test_ids = _get_entries(all_comment_ids, test)
        y_train = _get_entries(y, train)
        y_test = _get_entries(y, test)

        p_train = (y_train.count(1))/float(len(y_train))
        if verbose:
            print "p train: %s" % p_train
            print "p test: %s" % (y_test.count(1)/float(len(y_test)))

        if model=="baseline":
            import random
            # guess at chance
            def baseline_clf(): # no input!
                if random.random() < p_train:
                    return 1
                return -1

        test_comment_texts = _get_entries(comment_texts, test)
        test_comments.append(test_comment_texts)

        #pdb.set_trace()
        X_train, X_test = X[train], X[test]
        

        clf, preds = None, None
        if model=="baseline":
            preds = [baseline_clf() for i in xrange(X_test.shape[0])]
        else:
            svm = None
            if model=="SGD":
                svm = SGDClassifier(loss="hinge", penalty="l2", class_weight="auto", n_iter=2000)
                parameters = {'alpha':[.0001, .001, .01, .1]}
            else:
                svm = LinearSVC(loss="l2", class_weight="auto")
                parameters = {'C':[ .001, .01,  .1, 1, 10, 100]}
            
            clf = GridSearchCV(svm, parameters, scoring='f1')

            clf.fit(X_train, y_train)
            #print show_most_informative_features(vectorizer, clf.best_estimator_)
            #pdb.set_trace()
            preds = clf.predict(X_test)


        ids_to_preds = dict(zip(test_ids, preds))
        kappa = comment_level_computer_agreement_with_humans(ids_to_preds, verbose=verbose)
        avg_pw_kappas.append(kappa)

        tp, fp, tn, fn = 0,0,0,0
        N = len(preds)
        fn_comments, fp_comments = [], []
        if verbose:
            print N
        for i in xrange(N):
            cur_id = test_ids[i]
            y_i = y_test[i]
            pred_y_i = preds[i]

            if y_i == 1:
                # ironic
                if pred_y_i == 1:
                    tp += 1 
                else:
                    fn += 1
                    fn_comments.append(test_comment_texts[i])
            else:
                # unironic
                if pred_y_i == -1:
                    tn += 1
                else:
                    #pdb.set_trace()
                    fp += 1
                    fp_comments.append(test_comment_texts[i])

        
        recall = tp/float(tp + fn)
        try:
            precision = tp/float(tp + fp)
        except:
            print "precision undefined!"
            precision = 0.0
        recalls.append(recall)
        precisions.append(precision)

        try:
            f1 = 2* (precision * recall) / (precision + recall)
        except:
            print "f1 undefined!"
            f1 = 0.0
        Fs.append(f1)
        

       
        from sklearn.metrics import auc
        if not model=="baseline":
            probas = clf.decision_function(X_test)
            #probas = [x[1] for x in probas]
        else:
            probas = [random.random() for i in xrange(X_test.shape[0])]
        
        prec, recall, thresholds = precision_recall_curve(y_test, probas)
        area = auc(recall, prec)
        AUCs.append(area)
    
        #print show_most_informative_features(vectorizer, clf)
    #top_features.append(show_most_informative_features(vectorizer, clf))
    if verbose:
        clf = SGDClassifier(loss="hinge", penalty="l2", alpha=.001, class_weight="auto",n_iter=5000)
        #clf = sklearn.linear_model.LogisticRegression(penalty="l2", class_weight="auto")
        clf.fit(X, y)
        print show_most_informative_features(vectorizer, clf)

    avg = lambda x : sum(x)/float(len(x))
    print "-"*10
    print model
    print "-"*10
    print "\nrecalls:"
    print recalls
    print "average: %s" % avg(recalls)

    print "\nprecisions:"
    print precisions
    print "average: %s" % avg(precisions)

    print "\nF1s:"
    print Fs   
    print "average: %s" % avg(Fs)

    
    print "\nAUCs:"
    print AUCs
    print "average: %s" % avg(AUCs)
    
    print "\naverage kappas:"
    print avg_pw_kappas
    print "average average kappas: %s" % avg(avg_pw_kappas)


def add_punctuation_features(comment):
    # @TODO refactor -- obviously redundant with below! yuck
    # adding some features here
    emoticon_RE_str = '(?::|;|=)(?:-)?(?:\)|\(|D|P)'
    question_mark_RE_str = '\?'
    exclamation_point_RE_str = '\!'
    # any combination of multiple exclamation points and question marks
    interrobang_RE_str = '[\?\!]{2,}'

    #pdb.set_trace()
    if len(re.findall(r'%s' % emoticon_RE_str, comment)) > 0:
        comment = comment + " PUNCxEMOTICON"
    if len(re.findall(r'%s' % exclamation_point_RE_str, comment)) > 0:
        comment = comment + " PUNCxEXCLAMATION_POINT"
    if len(re.findall(r'%s' % question_mark_RE_str, comment)) > 0:
        comment = comment + " PUNCxQUESTION_MARK"
    if len(re.findall(r'%s' % interrobang_RE_str, comment)) > 0:
        comment = comment + " PUNCxINTERROBANG"
    
    if any([len(s) > 2 and unicode.isupper(s) for s in comment.split(" ")]):
        comment = comment + " PUNCxUPPERCASE" 

    return comment

def ml_bow():
    all_comment_ids = get_labeled_thrice_comments()

    ironic_comment_ids = get_ironic_comment_ids()
    #ironic_ids_str = _make_sql_list_str(ironic_comments)

    forced_decision_ids = _grab_single_element(cursor.execute(
                '''select distinct comment_id from irony_label where forced_decision=1 and labeler_id in %s;''' % 
                    labeler_id_str)) 

    comment_texts, y = [], []
    for id_ in all_comment_ids:
        comment_texts.append(grab_comments([id_])[0])
        if id_ in ironic_comment_ids:
            y.append(1)
        else:
            y.append(-1)

    # adding some features here
    emoticon_RE_str = '(?::|;|=)(?:-)?(?:\)|\(|D|P)'
    question_mark_RE_str = '\?'
    exclamation_point_RE_str = '\!'
    # any combination of multiple exclamation points and question marks
    interrobang_RE_str = '[\?\!]{2,}'

    for i, comment in enumerate(comment_texts):
        #pdb.set_trace()
        if len(re.findall(r'%s' % emoticon_RE_str, comment)) > 0:
            comment = comment + " PUNCxEMOTICON"
        if len(re.findall(r'%s' % exclamation_point_RE_str, comment)) > 0:
            comment = comment + " PUNCxEXCLAMATION_POINT"
        if len(re.findall(r'%s' % question_mark_RE_str, comment)) > 0:
            comment = comment + " PUNCxQUESTION_MARK"
        if len(re.findall(r'%s' % interrobang_RE_str, comment)) > 0:
            comment = comment + " PUNCxINTERROBANG"
        
        if any([len(s) > 2 and str.isupper(s) for s in comment.split(" ")]):
            comment = comment + " PUNCxUPPERCASE" 
        
        comment_texts[i] = comment
    # vectorize
    vectorizer = CountVectorizer(max_features=50000, ngram_range=(1,2), binary=True, stop_words="english")
    #vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(max_features=50000, 
    #                                                    ngram_range=(1,2), stop_words="english")
    X = vectorizer.fit_transform(comment_texts)
    kf = KFold(len(y), n_folds=5, shuffle=True)
    X_context, y_mistakes = [], []
    recalls, precisions = [], []
    Fs = []
    top_features = []
    for train, test in kf:
        train_ids = _get_entries(all_comment_ids, train)
        test_ids = _get_entries(all_comment_ids, test)
        y_train = _get_entries(y, train)
        y_test = _get_entries(y, test)

        X_train, X_test = X[train], X[test]
        svm = SGDClassifier(loss="hinge", penalty="l2", class_weight="auto", alpha=.01)
        #pdb.set_trace()
        parameters = {'alpha':[.001, .01,  .1, 1]}
        clf = GridSearchCV(svm, parameters, scoring='f1')
        clf.fit(X_train, y_train)
        preds = clf.predict(X_test)
        
        #precision, recall, f1, support = sklearn.metrics.precision_recall_fscore_support(y_test, preds)
        tp, fp, tn, fn = 0,0,0,0
        N = len(preds)

        for i in xrange(N):
            cur_id = test_ids[i]

            y_i = y_test[i]
            pred_y_i = preds[i]

            if cur_id in forced_decision_ids:
                X_context.append([y_i, 1])
            else:
                X_context.append([y_i, 0])

            if y_i == 1:
                # ironic
                if pred_y_i == 1:
                    # true positive
                    tp += 1 
                    y_mistakes.append(0)
                else:
                    # false negative
                    fn += 1
                    y_mistakes.append(1)
            else:
                # unironic
                if pred_y_i == -1:
                    # true negative
                    tn += 1
                    y_mistakes.append(0)
                else:
                    # false positive
                    fp += 1
                    y_mistakes.append(1)

        recall = tp/float(tp + fn)
        precision = tp/float(tp + fp)
        recalls.append(recall)
        precisions.append(precision)
        f1 = 2* (precision * recall) / (precision + recall)
        Fs.append(f1)
        #pdb.set_trace()
        #top_features.append(show_most_informative_features(vectorizer, clf))

    X_context = sm.add_constant(X_context, prepend=True)
    #pdb.set_trace()
    logit_mod = sm.Logit(y_mistakes, X_context)
    logit_res = logit_mod.fit()
    
    print logit_res.summary()
    #pdb.set_trace()
    clf = SGDClassifier(loss="hinge", penalty="l2", alpha=.01, class_weight="auto")
    clf.fit(X, y)
    print show_most_informative_features(vectorizer, clf)
    #top_features.append(show_most_informative_features(vectorizer, clf))

    print "recalls:"
    print recalls
    print "precisions:"
    print precisions
    print "F1s:"
    print Fs

def grab_comments(comment_id_list, verbose=False):
    comments_list = []
    for comment_id in comment_id_list:
        cursor.execute("select text from irony_commentsegment where comment_id='%s' order by segment_index" % comment_id)
        segments = _grab_single_element(cursor.fetchall())
        comment = " ".join(segments)
        if verbose:
            print comment
        comments_list.append(comment.encode('utf-8').strip())
    return comments_list

def show_most_informative_features(vectorizer, clf, n=100):
    c_f = sorted(zip(clf.coef_[0], vectorizer.get_feature_names()))
    top = zip(c_f[:n], c_f[:-(n+1):-1])
    out_str = []
    for (c1,f1),(c2,f2) in top:
        out_str.append("\t%.4f\t%-15s\t\t%.4f\t%-15s" % (c1,f1,c2,f2))
    return "\n".join(out_str)

################################################################################
# retreive NNP(S) words given a segment_id (id -> irony_comment_segment).
def get_NNPs_from_segment(segment_id):
    NNPs = []
    cursor.execute('select tag from irony_commentsegment where id=%s' % segment_id)
    tagged_sentence = cursor.fetchall()[0][0].encode('utf-8')
    word_tag_tuples = [nltk.tag.str2tuple(t) for t in tagged_sentence.split()]
    NNPs.extend(word_tag[0] for word_tag in word_tag_tuples if word_tag[1] == 'NNP' or word_tag[1] == 'NNPS')
    return NNPs

def is_segment_ironic(segment_id, at_least=2):
    cursor.execute('select label from irony_label where segment_id=%s and labeler_id in %s' % (segment_id, labeler_id_str))
    return cursor.fetchall().count((1,)) >= 2

import operator
def preliminary_test_with_NNPs():
    cursor.execute('select segment_id from irony_label group by segment_id having count(labeler_id) >= 3')
    ids = [t[0] for t in cursor.fetchall() if t[0] != None]
    ironic = {}
    unironic = {}
    for id in ids:
        NNPs = get_NNPs_from_segment(id)
        if len(NNPs) != 0:
            dict = ironic if is_segment_ironic(id) else unironic
            for word in NNPs:
                if word not in dict:
                    dict[word] = 0
                dict[word] += 1
    sorted_ironic = sorted(ironic.iteritems(), key=operator.itemgetter(1))
    sorted_ironic.reverse()
    print sorted_ironic[:20]
    sorted_unironic = sorted(unironic.iteritems(), key=operator.itemgetter(1))
    sorted_unironic.reverse()
    print sorted_unironic[:20]

def length_feature():
    cursor.execute('select segment_id from irony_label group by segment_id having count(labeler_id) >= 3')
    ids = [t[0] for t in cursor.fetchall() if t[0] != None]
    ironic = {}
    unironic = {}
    for id in ids:
        cursor.execute('select text from irony_commentsegment where id=%s' % id)
        tmp = len(cursor.fetchall()[0][0].encode('utf-8').split())
        dict = ironic if is_segment_ironic(id) else unironic
        if tmp not in dict:
            dict[tmp] = 0
        dict[tmp] += 1
    sorted_ironic = sorted(ironic.iteritems(), key=operator.itemgetter(1))
    sorted_ironic.reverse()
    print 'ironic'
    print sorted_ironic[:20]
    mean = 0.
    denom = 0
    for length, count in sorted_ironic:
        mean += count * length
        denom += count
    print mean / denom
        
    sorted_unironic = sorted(unironic.iteritems(), key=operator.itemgetter(1))
    sorted_unironic.reverse()
    print sorted_unironic[:20]
    mean = 0.
    denom = 0
    for length, count in sorted_unironic:
        mean += count * length
        denom += count
    print mean / denom

def get_labeled_thrice_segments():
    cursor.execute('select segment_id from irony_label group by segment_id having count(labeler_id) >= 3')
    thricely_labeled_segment_ids = _grab_single_element(cursor.fetchall())
    # TODO: The original somehow contains None. Figure out why.
    return thricely_labeled_segment_ids[1:]

def get_texts_and_labels(segment_ids):
    texts = []
    labels = []
    for segment_id in segment_ids:
        cursor.execute('select text from irony_commentsegment where id=%s' % segment_id)
        texts.append(cursor.fetchall()[0][0].encode('utf-8'))
        if is_segment_ironic(segment_id):
            labels.append(1)
        else:
            labels.append(-1)
        
    return texts, labels

def experiment(model="SGD", verbose=False):
    labeled_segment_ids = get_labeled_thrice_segments()
    segment_texts, y = get_texts_and_labels(labeled_segment_ids)

    vectorizer = sklearn.feature_extraction.text.TfidfVectorizer(
                                        max_features=10000, ngram_range=(1,2), 
                                        stop_words="english")
    X = vectorizer.fit_transform(segment_texts)
    
    x0 = scipy.sparse.csr.csr_matrix(np.zeros((X.shape[0], 4)))
    X = scipy.sparse.hstack((X, x0)).tocsr()
    
    #pdb.set_trace()
    kf = KFold(len(y), n_folds=5, shuffle=True, random_state=5)
    recalls, precisions, Fs, AUCs = [], [], [], []
    avg_pw_kappas = []
    test_comments = []

    for train, test in kf:
        train_ids = _get_entries(labeled_segment_ids, train)
        test_ids = _get_entries(labeled_segment_ids, test)
        y_train = _get_entries(y, train)
        y_test = _get_entries(y, test)

        p_train = (y_train.count(1))/float(len(y_train))
        if verbose:
            print "p train: %s" % p_train
            print "p test: %s" % (y_test.count(1)/float(len(y_test)))

        if model=="baseline":
            import random
            # guess at chance
            def baseline_clf(): # no input!
                if random.random() < p_train:
                    return 1
                return -1

        test_comment_texts = _get_entries(segment_texts, test)
        test_comments.append(test_comment_texts)

        #pdb.set_trace()
        X_train, X_test = X[train], X[test]
        

        clf, preds = None, None
        if model=="baseline":
            preds = [baseline_clf() for i in xrange(X_test.shape[0])]
        else:
            svm = None
            if model=="SGD":
                svm = SGDClassifier(loss="hinge", penalty="l2", class_weight="auto", n_iter=2000)
                parameters = {'alpha':[.0001, .001, .01, .1]}
            else:
                svm = LinearSVC(loss="l2", class_weight="auto")
                parameters = {'C':[ .001, .01,  .1, 1, 10, 100]}
            
            clf = GridSearchCV(svm, parameters, scoring='f1')

            clf.fit(X_train, y_train)
            #print show_most_informative_features(vectorizer, clf.best_estimator_)
            #pdb.set_trace()
            preds = clf.predict(X_test)


        ids_to_preds = dict(zip(test_ids, preds))
        kappa = comment_level_computer_agreement_with_humans(ids_to_preds, verbose=verbose)
        avg_pw_kappas.append(kappa)

        tp, fp, tn, fn = 0,0,0,0
        N = len(preds)
        fn_comments, fp_comments = [], []
        if verbose:
            print N
        for i in xrange(N):
            cur_id = test_ids[i]
            y_i = y_test[i]
            pred_y_i = preds[i]

            if y_i == 1:
                # ironic
                if pred_y_i == 1:
                    tp += 1 
                else:
                    fn += 1
                    fn_comments.append(test_comment_texts[i])
            else:
                # unironic
                if pred_y_i == -1:
                    tn += 1
                else:
                    #pdb.set_trace()
                    fp += 1
                    fp_comments.append(test_comment_texts[i])

        
        recall = tp/float(tp + fn)
        try:
            precision = tp/float(tp + fp)
        except:
            print "precision undefined!"
            precision = 0.0
        recalls.append(recall)
        precisions.append(precision)

        try:
            f1 = 2* (precision * recall) / (precision + recall)
        except:
            print "f1 undefined!"
            f1 = 0.0
        Fs.append(f1)
        

       
        from sklearn.metrics import auc
        if not model=="baseline":
            probas = clf.decision_function(X_test)
            #probas = [x[1] for x in probas]
        else:
            probas = [random.random() for i in xrange(X_test.shape[0])]
        
        prec, recall, thresholds = precision_recall_curve(y_test, probas)
        area = auc(recall, prec)
        AUCs.append(area)
    
        #print show_most_informative_features(vectorizer, clf)
    #top_features.append(show_most_informative_features(vectorizer, clf))
    if verbose:
        clf = SGDClassifier(loss="hinge", penalty="l2", alpha=.001, class_weight="auto",n_iter=5000)
        #clf = sklearn.linear_model.LogisticRegression(penalty="l2", class_weight="auto")
        clf.fit(X, y)
        print show_most_informative_features(vectorizer, clf)

    avg = lambda x : sum(x)/float(len(x))
    print "-"*10
    print model
    print "-"*10
    print "\nrecalls:"
    print recalls
    print "average: %s" % avg(recalls)

    print "\nprecisions:"
    print precisions
    print "average: %s" % avg(precisions)

    print "\nF1s:"
    print Fs   
    print "average: %s" % avg(Fs)

    
    print "\nAUCs:"
    print AUCs
    print "average: %s" % avg(AUCs)
    
    print "\naverage kappas:"
    print avg_pw_kappas
    print "average average kappas: %s" % avg(avg_pw_kappas)
