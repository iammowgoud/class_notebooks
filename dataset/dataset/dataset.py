import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import statsmodels.api as sm
import warnings

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, PowerTransformer, \
    OneHotEncoder
from sklearn_pandas import DataFrameMapper
from scipy.stats import skew, boxcox_normmax
from scipy.special import boxcox1p

from dataset.split import Split
from dataset.correlations import cramers_v


warnings.simplefilter(action='ignore')

#
# Correlation ideas taken from:
# https://towardsdatascience.com/the-search-for-categorical-correlation-a1cf7f1888c9
#


class Dataset:
    """
    This class allows a simpler representation of the dataset used
    to build a model in class. It allows loading a remote CSV by
    providing an URL to the initialization method of the object.

        my_data = Dataset(URL)
        
    """
    
    meta = None
    data = None
    target = None
    features = None

    meta_tags = ['all', 'numerical', 'categorical', 'complete',
                 'numerical_na', 'categorical_na', 'features', 'target']

    def __init__(self, data_location=None, data_frame=None, *args, **kwargs):
        """
        Wrapper over the method read_csv from pandas, so you can user variadic
        arguments, as if you were using the actual read_csv
        :param data_location: path or url to the file
        :param data_frame: in case this method is called from the class method
        this parameter is passing the actual dataframe to read data from
        :param args: variadic unnamed arguments to pass to read_csv
        :param kwargs: variadic named arguments to pass to read_csv
        """
        if data_location is not None:
            self.data = pd.read_csv(data_location, *args, **kwargs)
        else:
            if data_frame is not None:
                self.data = data_frame
            else:
                raise RuntimeError(
                    "No data location, nor DataFrame passed to constructor")
        self.features = self.data.copy()
        self.metainfo()

    @classmethod
    def from_dataframe(cls, df):
        return cls(data_location=None, data_frame=df)
        
    def set_target(self, target_name):
        """
        Set the target variable for this dataset. This will create a new
        property of the object called 'target' that will contain the 
        target column of the dataset, and that column will be removed
        from the list of features.
        Example:
        
            my_data.set_target('SalePrice')
            
        """
        if target_name in list(self.features):
            self.target = self.features.loc[:, target_name].copy()
            self.features.drop(target_name, axis=1, inplace=True)
        else:
            self.target = self.data.loc[:, target_name].copy()
        self.metainfo()
        return self
        
    def test():
        return "test"

    def metainfo(self):
        """
        Builds metainfromation about the dataset, considering the 
        features that are categorical, numerical or does/doesn't contain NA's.
        """
        meta = dict()
        
        # Build the subsets per data ype (list of names)
        descr = pd.DataFrame({'dtype': self.features.dtypes, 
                              'NAs': self.features.isna().sum()})
        categorical_features = descr.loc[descr['dtype'] == 'object'].\
            index.values.tolist()
        numerical_features = descr.loc[descr['dtype'] != 'object'].\
            index.values.tolist()
        numerical_features_na = descr.loc[(descr['dtype'] != 'object') & 
                                          (descr['NAs'] > 0)].\
            index.values.tolist()
        categorical_features_na = descr.loc[(descr['dtype'] == 'object') & 
                                            (descr['NAs'] > 0)].\
            index.values.tolist()
        complete_features = descr.loc[descr['NAs'] == 0].index.values.tolist()
        
        # Update META-information
        meta['description'] = descr
        meta['all'] = list(self.data)
        meta['features'] = list(self.features)
        meta['target'] = self.target.name if self.target is not None else None
        meta['categorical'] = categorical_features
        meta['categorical_na'] = categorical_features_na
        meta['numerical'] = numerical_features
        meta['numerical_na'] = numerical_features_na
        meta['complete'] = complete_features
        self.meta = meta
        return self
    
    def outliers(self):
        """
        Find outliers, using bonferroni criteria, from the numerical features.
        Returns a list of indices where outliers are present
        """
        ols = sm.OLS(endog = self.target, exog = self.select('numerical'))
        fit = ols.fit()
        test = fit.outlier_test()['bonf(p)']
        return list(test[test<1e-3].index)

    def scale(self, features_of_type='numerical', return_series=False):
        """
        Scales numerical features in the dataset, unless the parameter 'what'
        specifies any other subset selection primitive.
        :param features_of_type: Subset selection primitive
        :return: the subset scaled.
        """
        assert features_of_type in self.meta_tags
        subset = self.select(features_of_type)
        mapper = DataFrameMapper([(subset.columns, StandardScaler())])
        scaled_features = mapper.fit_transform(subset.copy())
        self.features[self.names(features_of_type)] = pd.DataFrame(
            scaled_features,
            index=subset.index,
            columns=subset.columns)
        self.metainfo()
        if return_series is True:
            return self.features[self.names(features_of_type)]
        else:
            return self

    def ensure_normality(self,
                         features_of_type='numerical',
                         return_series=False):
        """
        Ensures that the numerical features in the dataset, unless the
        parameter 'what' specifies any other subset selection primitive,
        fit into a normal distribution by applying the Yeo-Johnson transform
        :param features_of_type: Subset selection primitive
        :param return_series: Return the normalized series
        :return: the subset fitted to normal distribution.
        """
        assert features_of_type in self.meta_tags
        subset = self.select(features_of_type)
        mapper = DataFrameMapper([(subset.columns, PowerTransformer(
            method='yeo-johnson',
            standardize=False))])
        normed_features = mapper.fit_transform(subset.copy())
        self.features[self.names(features_of_type)] = pd.DataFrame(
            normed_features,
            index=subset.index,
            columns=subset.columns)
        self.metainfo()
        if return_series is True:
            return self.features[self.names(features_of_type)]
    
    def skewness(self, threshold=0.75, fix=False, return_series=False):
        """
        Returns the list of numerical features that present skewness
        :return: A pandas Series with the features and their skewness
        """
        df = self.select('numerical')
        feature_skew = df.apply(
            lambda x: skew(x)).sort_values(ascending=False)

        if fix is True:
            high_skew = feature_skew[feature_skew > threshold]
            skew_index = high_skew.index
            for feature in skew_index:
                self.features[feature] = boxcox1p(
                    df[feature], boxcox_normmax(df[feature] + 1))
        if return_series is True:
            return feature_skew

    def onehot_encode(self):
        """
        Encodes the categorical features in the dataset, with OneHotEncode
        """
        new_df = self.features[self.names('numerical')].copy()
        for categorical_column in self.names('categorical'):
            new_df = pd.concat(
                [new_df,
                 pd.get_dummies(
                     self.features[categorical_column],
                     prefix=categorical_column)
                 ],
                axis=1)
        self.features = new_df.copy()
        self.metainfo()
        return self

    def correlated(self, threshold=0.9):
        """
        Return the features that are highly correlated to with other
        variables, either numerical or categorical, based on the threshold. For
        numerical variables Spearman correlation is used, for categorical
        cramers_v
        :param threshold: correlation limit above which features are considered
                          highly correlated.
        :return: the list of features that are highly correlated, and should be
                 safe to remove.
        """
        corr_categoricals, _ = self.categorical_correlated(threshold)
        corr_numericals, _ = self.numerical_correlated(threshold)
        return corr_categoricals + corr_numericals

    def numerical_correlated(self,
                             threshold=0.9):
        """
        Build a correlation matrix between all the features in data set
        :param subset: Specify which subset of features use to build the
        correlation matrix. Default 'features'
        :param method: Method used to build the correlation matrix.
        Default is 'Spearman' (Other options: 'Pearson')
        :param threshold: Threshold beyond which considering high correlation.
        Default is 0.9
        :return: The list of columns that are highly correlated and could be
        droped out from dataset.
        """
        corr_matrix = np.absolute(
            self.select('numerical').corr(method='spearman')).abs()
        # Select upper triangle of correlation matrix
        upper = corr_matrix.where(
            np.triu(np.ones(corr_matrix.shape), k=1).astype(np.bool))
        # Find index of feature columns with correlation greater than threshold
        return [column for column in upper.columns
                   if any(abs(upper[column]) > threshold)], corr_matrix

    def categorical_correlated(self, threshold=0.9):
        """
        Generates a correlation matrix for the categorical variables in dataset
        :param threshold: Limit from which correlations is considered high.
        :return: the list of categorical variables with HIGH correlation and
        the correlation matrix
        """
        columns = self.meta['categorical']
        corr = pd.DataFrame(index=columns, columns=columns)
        for i in range(0, len(columns)):
            for j in range(i, len(columns)):
                if i == j:
                    corr[columns[i]][columns[j]] = 1.0
                else:
                    cell = cramers_v(self.features[columns[i]],
                                     self.features[columns[j]])
                    corr[columns[i]][columns[j]] = cell
                    corr[columns[j]][columns[i]] = cell
        corr.fillna(value=np.nan, inplace=True)
        # Select upper triangle of correlation matrix
        upper = corr.where(
            np.triu(np.ones(corr.shape), k=1).astype(np.bool))
        # Find index of feature columns with correlation greater than threshold
        return [column for column in upper.columns
                   if any(abs(upper[column]) > threshold)], corr

    def under_represented_features(self, threshold=0.98):
        """
        Returns the list of categorical features with unrepresented categories
        or a clear unbalance between the values that can take.
        :param threshold: The upper limit of the most represented category
        of the feature.
        :return: the list of features that with unrepresented categories.
        """
        under_rep = []
        for column in self.meta['categorical']:
            counts = self.features[column].value_counts()
            majority_freq = counts.iloc[0]
            if (majority_freq / len(self.features)) > threshold:
                under_rep.append(column)
        return under_rep

    def stepwise_selection(self,
                           initial_list=None,
                           threshold_in=0.01,
                           threshold_out=0.05,
                           verbose=True):
        """
        Perform a forward-backward feature selection based on p-value from
        statsmodels.api.OLS
        Your features must be all numerical, so be sure to onehot_encode them
        before calling this method.
        Always set threshold_in < threshold_out to avoid infinite looping.

        Arguments:
            initial_list - list of features to start with (column names of X)
            threshold_in - include a feature if its p-value < threshold_in
            threshold_out - exclude a feature if its p-value > threshold_out
            verbose - whether to print the sequence of inclusions and exclusions

        Returns: list of selected features

        See https://en.wikipedia.org/wiki/Stepwise_regression for the details
        Taken from: https://datascience.stackexchange.com/a/24823
        """
        if initial_list is None:
            initial_list = []
        assert len(self.names('categorical')) == 0
        included = list(initial_list)
        while True:
            changed = False
            # forward step
            excluded = list(set(self.features.columns) - set(included))
            new_pval = pd.Series(index=excluded)
            for new_column in excluded:
                model = sm.OLS(self.target, sm.add_constant(
                    pd.DataFrame(self.features[included + [new_column]]))).fit()
                new_pval[new_column] = model.pvalues[new_column]
            best_pval = new_pval.min()
            if best_pval < threshold_in:
                best_feature = new_pval.idxmin()
                included.append(best_feature)
                changed = True
                if verbose:
                    print('Add  {:30} with p-value {:.6}'.format(best_feature,
                                                                 best_pval))
            # backward step
            model = sm.OLS(self.target, sm.add_constant(
                pd.DataFrame(self.features[included]))).fit()
            # use all coefs except intercept
            pvalues = model.pvalues.iloc[1:]
            worst_pval = pvalues.max()  # null if p-values is empty
            if worst_pval > threshold_out:
                changed = True
                worst_feature = pvalues.argmax()
                included.remove(worst_feature)
                if verbose:
                    print('Drop {:30} with p-value {:.6}'.format(worst_feature,
                                                                 worst_pval))
            if not changed:
                break
        return included

    #
    # From this point, the methods are related to data manipulation of the
    # pandas dataframe.
    #

    def select(self, which):
        """
        Returns a subset of the columns of the dataset.
        `which` specifies which subset of features to return
        If it is a list, it returns those feature names in the list,
        And if it is a keywork from: 'all', 'categorical', 'categorical_na',
        'numerical', 'numerical_na', 'complete', 'features', 'target',
        then the list of features is extracted from the metainformation
        of the dataset.
        """
        if isinstance(which, list):
            return self.features.loc[:, which]
        else:
            assert which in self.meta_tags
            return self.features.loc[:, self.meta[which]]

    def names(self, which='all'):
        """
        Returns a the names of the columns of the dataset for which the arg
        `which` is specified.
        If it is a list, it returns those feature names in the list,
        And if it is a keywork from: 'all', 'categorical', 'categorical_na',
        'numerical', 'numerical_na', 'complete', then the list of
        features is extracted from the metainformation of the dataset.
        """
        assert which in self.meta_tags
        return self.meta[which]

    def add_column(self, serie):
        """
        Add a Series as a new column to the dataset.
        Example:

            my_data.add_column(serie)
            my_data.add_column(name=pandas.Series().values)
        """
        if serie.name not in self.names('features'):
            self.features[serie.name] = serie.values
            self.metainfo()
        return self

    def drop_columns(self, columns_list):
        """
        Drop one or a list of columns from the dataset.
        Example:
        
            my_data.drop_columns('column_name')
            my_data.drop_columns(['column1', 'column2', 'column3'])
        """
        if isinstance(columns_list, list) is not True:
            columns_list = [columns_list]
        for column in columns_list:
            if column in self.names('features'):
                self.features.drop(column, axis=1, inplace=True)
        self.metainfo()
        return self

    def keep_columns(self, to_keep):
        """
        Keep only one or a list of columns from the dataset.
        Example:

            my_data.keep_columns('column_name')
            my_data.keep_columns(['column1', 'column2', 'column3'])
        """
        if isinstance(to_keep, list) is not True:
            to_keep = [to_keep]
        to_drop = list(set(list(self.features)) - set(to_keep))
        self.drop_columns(to_drop)
        return self

    def aggregate(self,
                  col_list,
                  new_column,
                  operation='sum',
                  drop_columns=True):
        """
        Perform an arithmetic operation on the given columns, and places the
        result on a new column, removing the original ones.

        Example: if we want to sum the values of column1 and column2 into a
        new column called 'column3', we use:

            my_data.aggregate(['column1', 'column2'], 'column3')

        As a result, 'my_data' will remove 'column1' and 'column2', and the
        operation will be the sum of the values, as it is the default operation.

        :param col_list: the list of columns over which the operation is done
        :param new_column: the name of the new column to be generated from the
        operation
        :param drop_columns: whether remove the columns used to perfrom the
        aggregation
        :param operation: the operation to be done over the column values for
        each row. Examples: 'sum', 'diff', 'max', etc. By default, the operation
        is the sum of the values.
        :return: the Dataset object
        """
        assert operation in dir(type(self.features))
        for col_name in col_list:
            assert col_name in list(self.features)
        self.features[new_column] = getattr(
            self.features[col_list],
            operation)(axis=1)
        if drop_columns is True:
            self.drop_columns(col_list)
        else:
            self.metainfo()
        return self

    def drop_samples(self, index_list):
        """
        Remove the list of samples from the dataset. 
        """
        self.data.drop(self.data.index[index_list])
        self.metainfo()
        return self
        
    def replace_na(self, column, value):
        """
        Replace any NA occurrence from the column or list of columns passed 
        by the value passed as second argument.
        """
        if isinstance(column, list) is True:
            for col in column:
                self.data[col].fillna(value, inplace=True)
        else:
            self.data[column].fillna(value, inplace=True)
        self.metainfo()
        return self
        
    def split(self,
              seed=1024, 
              test_size=0.2, 
              validation_split=False):
        """
        From an input dataframe, separate features from target, and 
        produce splits (with or without validation).
        """
        assert self.target is not None
        
        X = pd.DataFrame(self.features, columns=self.names('features'))
        Y = pd.DataFrame(self.target)

        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y, 
            test_size=test_size, random_state=seed)

        if validation_split is True:
            X_train, X_val, Y_train, Y_val = train_test_split(
                X_train, Y_train, 
                test_size=test_size, random_state=seed)
            X_splits = [X_train, X_test, X_val]
            Y_splits = [Y_train, Y_test, Y_val]
        else:
            X_splits = [X_train, X_test]
            Y_splits = [Y_train, Y_test]

        return Split(X_splits), Split(Y_splits)

    def describe(self):
        """
        Printout the metadata information collected when calling the
        metainfo() method.
        """
        if self.meta is None:
            self.metainfo()

        print('\nAvailable types:', self.meta['description']['dtype'].unique())
        print('{} Features'.format(len(self.meta['features'])))
        print('{} categorical features'.format(
            len(self.meta['categorical'])))
        print('{} numerical features'.format(
            len(self.meta['numerical'])))
        print('{} categorical features with NAs'.format(
            len(self.meta['categorical_na'])))
        print('{} numerical features with NAs'.format(
            len(self.meta['numerical_na'])))
        print('{} Complete features'.format(
            len(self.meta['complete'])))
        print('--')
        print('Target: {}'.format(
            self.meta['target'] if self.target is not None else 'Not set'))

    def table(self, which='all', max_width=80):
        """
        Print a tabulated version of the list of elements in a list, using
        a max_width display (default 80).
        """
        assert which in self.meta_tags

        f_list = self.names(which)
        if len(f_list) == 0:
            return

        num_features = len(f_list)
        max_length = max([len(feature) for feature in f_list])
        max_fields = int(np.floor(max_width / (max_length + 1)))
        col_width = max_length + 1

        print('-' * ((max_fields * max_length) + (max_fields - 1)))
        for field_idx in range(int(np.ceil(num_features / max_fields))):
            from_idx = field_idx * max_fields
            to_idx = (field_idx * max_fields) + max_fields
            if to_idx > num_features:
                to_idx = num_features
            format_str = ''
            for i in range(to_idx - from_idx):
                format_str += '{{:<{:d}}}'.format(col_width)
            print(format_str.format(*f_list[from_idx:to_idx]))
        print('-' * ((max_fields * max_length) + (max_fields - 1)))

    def plot_corr_matrix(self, corr_matrix):
        plt.subplots(figsize=(11, 9))
        # Generate a mask for the upper triangle
        mask = np.zeros_like(corr_matrix, dtype=np.bool)
        mask[np.triu_indices_from(mask)] = True
        cmap = sns.diverging_palette(220, 10, as_cmap=True)
        sns.heatmap(corr_matrix, mask=mask, cmap=cmap, vmax=0.75, center=0,
                    square=True, linewidths=.5, cbar_kws={"shrink": .5});
        plt.show();

    def plot_against_target(self, columns_list, bins=50):
        """
        Plots a histogram of all (or a specific) feature
        Example:
            my_data.drop_columns('column_name')
            my_data.drop_columns(['column1', 'column2', 'column3'])
        :param which: feature to plot
        :return: A plot of the feature histogram
        """
        assert self.names('target') is not None, "Please set the target variable first"
        target_name = self.names('target')

        if isinstance(columns_list, list) is not True:
            columns_list = [columns_list]

        plt.rcParams["figure.figsize"] = (15,15)


        for i, column in enumerate(columns_list):
            if column in self.names('features') and column in self.names('numerical'):
                # Prepare series
                data = self.select([column, target_name]).copy()
                data = pd.concat([self.select([column]), self.target], axis=1)
                x = data.loc[data[target_name]==0][column]
                y = data.loc[data[target_name]==1][column]

                # calculate number of bins
                unique = len(np.unique(data))
                number_of_bins = unique if unique <= bins else bins

                # Plot arrangment
                plt.subplot(len(columns_list), 1,i+1)
                
                # Plot
                plt.hist([x,y], bins=number_of_bins, stacked=True)
                
                # Add labels
                plt.title('Histogram of ' + column)
                plt.legend([target_name+': 0', target_name+': 1'])
                plt.xlabel(column)
                plt.ylabel('count')