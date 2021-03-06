from setuptools import setup, find_packages


setup(
    name='hh-page-clf',
    url='https://github.com/TeamHG-Memex/hh-page-classifier',
    packages=find_packages(exclude=['tests']),
    include_package_data=True,
    install_requires=[
        'attrs',
        'eli5>=0.7',
        'html-text',
        'json_lines>=0.2.0',
        'kafka-python==1.3.3',
        'langdetect',
        'numpy',
        'pandas',
        'requests',
        'scikit-learn>=0.18<0.19',
        'scipy==0.18.1',
        'stop-words',
        'tldextract',
        'tqdm',
        'ujson',
        'xgboost>=0.6a2',
    ],
    entry_points={
        'console_scripts': [
            'hh-page-clf-service=hh_page_clf.service:main',
            'hh-page-clf-train=hh_page_clf.train:main',
            'train-lda=hh_page_clf.pretraining.train_lda:main',
            'train-doc2vec=hh_page_clf.pretraining.train_doc2vec:main',
            'extract-texts=hh_page_clf.pretraining.extract_texts:main',
            'dmoz-to-csv=hh_page_clf.pretraining.dmoz_reader:to_csv',
            'dmoz-to-fasttext=hh_page_clf.pretraining.dmoz_fasttext:main',
        ],
    },
    classifiers=[
        'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
    ],
)
