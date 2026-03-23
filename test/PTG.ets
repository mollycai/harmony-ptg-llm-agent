const PTGJson = `{
  "pages/MainPage": [
    {
      "component": {
        "type": "GridItem"
      },
      "event": "onClick",
      "target": "pages/categoryDetail/CategoryDetailPage"
    },
    {
      "component": {
        "type": "ListItem"
      },
      "event": "onClick",
      "target": "pages/commonDetail/DetailPage"
    },
    {
      "component": {
        "type": "ListItem"
      },
      "event": "onClick",
      "target": "pages/topicDetail/TopicDetailPage"
    },
    {
      "component": {
        "type": "__Common__"
      },
      "event": "onClick",
      "target": "pages/commonDetail/DetailPage"
    },
    {
      "component": {
        "type": "Stack"
      },
      "event": "onClick",
      "target": "pages/container/ContainerPage"
    },
    {
      "component": {
        "type": "Stack"
      },
      "event": "onClick",
      "target": "pages/test/TestPage"
    },
    {
      "component": {
        "type": "Stack"
      },
      "event": "onClick",
      "target": "pages/hot/CoordinatePage"
    },
    {
      "component": {
        "type": "Stack"
      },
      "event": "onClick",
      "target": "pages/test/TestHorizontalPage"
    },
    {
      "component": {
        "type": "Stack"
      },
      "event": "onClick",
      "target": "pages/test/TestHorizontalPage2"
    }
  ],
  "pages/SplashPage": [
    {
      "component": {
        "type": "SplashPage"
      },
      "event": "aboutToAppear",
      "target": "pages/MainPage"
    }
  ],
  "pages/categoryDetail/CategoryDetailPage": [
    {
      "component": {
        "type": "ListItem"
      },
      "event": "onClick",
      "target": "pages/commonDetail/DetailPage"
    }
  ],
  "pages/commonDetail/DetailPage": [],
  "pages/container/ContainerPage": [
    {
      "component": {
        "type": "GridItem"
      },
      "event": "onClick",
      "target": "pages/categoryDetail/CategoryDetailPage"
    },
    {
      "component": {
        "type": "ListItem"
      },
      "event": "onClick",
      "target": "pages/commonDetail/DetailPage"
    },
    {
      "component": {
        "type": "ListItem"
      },
      "event": "onClick",
      "target": "pages/topicDetail/TopicDetailPage"
    }
  ],
  "pages/hot/CoordinatePage": [
    {
      "component": {
        "type": "ListItem"
      },
      "event": "onClick",
      "target": "pages/commonDetail/DetailPage"
    }
  ],
  "pages/test/TestHorizontalPage": [],
  "pages/test/TestHorizontalPage2": [],
  "pages/test/TestPage": [],
  "pages/topicDetail/TopicDetailPage": []
}`;
export default PTGJson;
